# Copyright 2021-2023, Francis Clairicia-Rose-Claire-Josephine
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
#
"""Low-level asynchronous stream servers module"""

from __future__ import annotations

__all__ = ["AsyncStreamClient", "AsyncStreamServer"]

import contextlib
from collections.abc import AsyncGenerator, Callable, Mapping
from typing import Any, Generic, NoReturn

from .... import protocol as protocol_module
from ...._typevars import _RequestT, _ResponseT
from ... import _stream, _utils, typed_attr
from ..backend.abc import AsyncBackend, TaskGroup
from ..transports import abc as transports, utils as transports_utils
from ._tools.actions import ActionIterator as _ActionIterator


class AsyncStreamClient(typed_attr.TypedAttributeProvider, Generic[_ResponseT]):
    __slots__ = (
        "__transport",
        "__producer",
        "__send_guard",
        "__weakref__",
    )

    def __init__(self, transport: transports.AsyncStreamWriteTransport, producer: _stream.StreamDataProducer[_ResponseT]) -> None:
        super().__init__()

        self.__transport: transports.AsyncStreamWriteTransport = transport
        self.__producer: _stream.StreamDataProducer[_ResponseT] = producer
        self.__send_guard: _utils.ResourceGuard = _utils.ResourceGuard("another task is currently sending data on this endpoint")

    def is_closing(self) -> bool:
        """
        Checks if the endpoint is closed or in the process of being closed.

        Returns:
            :data:`True` if the endpoint is closed.
        """
        return self.__transport.is_closing()

    async def aclose(self) -> None:
        """
        Closes the endpoint.
        """
        await self.__transport.aclose()
        self.__producer.clear()

    async def send_packet(self, packet: _ResponseT) -> None:
        """
        Sends `packet` to the remote endpoint.

        Warning:
            In the case of a cancellation, it is impossible to know if all the packet data has been sent.
            This would leave the connection in an inconsistent state.

        Parameters:
            packet: the Python object to send.
        """
        with self.__send_guard:
            transport = self.__transport
            producer = self.__producer

            producer.enqueue(packet)
            del packet
            await transport.send_all_from_iterable(producer)

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__transport.extra_attributes


class AsyncStreamServer(typed_attr.TypedAttributeProvider, Generic[_RequestT, _ResponseT]):
    __slots__ = (
        "__listener",
        "__protocol",
        "__max_recv_size",
        "__backend",
        "__serve_guard",
        "__weakref__",
    )

    def __init__(
        self,
        listener: transports.AsyncListener[transports.AsyncStreamTransport],
        protocol: protocol_module.StreamProtocol[_ResponseT, _RequestT],
        max_recv_size: int,
        *,
        backend: str | AsyncBackend | None = None,
        backend_kwargs: Mapping[str, Any] | None = None,
    ) -> None:
        if not isinstance(listener, transports.AsyncListener):
            raise TypeError(f"Expected an AsyncListener object, got {listener!r}")
        if not isinstance(protocol, protocol_module.StreamProtocol):
            raise TypeError(f"Expected a StreamProtocol object, got {protocol!r}")
        if not isinstance(max_recv_size, int) or max_recv_size <= 0:
            raise ValueError("'max_recv_size' must be a strictly positive integer")

        from ..backend.factory import AsyncBackendFactory

        backend = AsyncBackendFactory.ensure(backend, backend_kwargs)

        self.__listener: transports.AsyncListener[transports.AsyncStreamTransport] = listener
        self.__protocol: protocol_module.StreamProtocol[_ResponseT, _RequestT] = protocol
        self.__max_recv_size: int = max_recv_size
        self.__backend: AsyncBackend = backend
        self.__serve_guard: _utils.ResourceGuard = _utils.ResourceGuard("another task is currently accepting new connections")

    def is_closing(self) -> bool:
        """
        Checks if the server is closed or in the process of being closed.

        Returns:
            :data:`True` if the server is closed.
        """
        return self.__listener.is_closing()

    async def aclose(self) -> None:
        """
        Closes the server.
        """
        await self.__listener.aclose()

    async def serve(
        self,
        client_connected_cb: Callable[[AsyncStreamClient[_ResponseT]], AsyncGenerator[None, _RequestT]],
        task_group: TaskGroup | None = None,
    ) -> NoReturn:
        with self.__serve_guard:
            handler = _utils.prepend_argument(client_connected_cb)(self.__client_coroutine)
            async with self.__ensure_task_group(task_group) as task_group:
                await self.__listener.serve(handler, task_group)

    def get_backend(self) -> AsyncBackend:
        """
        Return the underlying backend interface.
        """
        return self.__backend

    def __ensure_task_group(self, task_group: TaskGroup | None) -> contextlib.AbstractAsyncContextManager[TaskGroup]:
        if task_group is None:
            return self.__backend.create_task_group()
        return contextlib.nullcontext(task_group)

    async def __client_coroutine(
        self,
        client_connected_cb: Callable[[AsyncStreamClient[_ResponseT]], AsyncGenerator[None, _RequestT]],
        transport: transports.AsyncStreamTransport,
    ) -> None:
        if not isinstance(transport, transports.AsyncStreamTransport):
            raise TypeError(f"Expected an AsyncStreamTransport object, got {transport!r}")

        async with contextlib.AsyncExitStack() as client_exit_stack:
            client_exit_stack.push_async_callback(transports_utils.aclose_forcefully, self.__backend, transport)

            producer = _stream.StreamDataProducer(self.__protocol)
            consumer = _stream.StreamDataConsumer(self.__protocol)
            client = AsyncStreamClient(transport, producer)

            client_exit_stack.callback(consumer.clear)
            client_exit_stack.callback(producer.clear)

            request_handler_generator = client_connected_cb(client)

            del client_exit_stack, client_connected_cb, client

            async with contextlib.aclosing(request_handler_generator):
                try:
                    await anext(request_handler_generator)
                except StopAsyncIteration:
                    return

                request_factory = _utils.make_callback(self.__request_factory, transport, consumer, self.__max_recv_size)
                async for action in _ActionIterator(request_factory):
                    try:
                        await action.asend(request_handler_generator)
                    except StopAsyncIteration:
                        return
                    finally:
                        del action

    @classmethod
    async def __request_factory(
        cls,
        transport: transports.AsyncStreamReadTransport,
        consumer: _stream.StreamDataConsumer[_RequestT],
        bufsize: int,
        /,
    ) -> _RequestT:
        while not transport.is_closing():
            try:
                return next(consumer)
            except StopIteration:
                pass
            data: bytes = await transport.recv(bufsize)
            if not data:  # Closed connection (EOF)
                break
            try:
                consumer.feed(data)
            finally:
                del data
        raise StopAsyncIteration

    @property
    def max_recv_size(self) -> int:
        """Read buffer size. Read-only attribute."""
        return self.__max_recv_size

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__listener.extra_attributes
