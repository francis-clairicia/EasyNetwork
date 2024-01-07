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
import dataclasses
from collections.abc import AsyncGenerator, Callable, Iterator, Mapping
from typing import Any, Generic, NoReturn, Self

from .... import protocol as protocol_module
from ...._typevars import _T_Request, _T_Response
from ....exceptions import UnsupportedOperation
from ... import _asyncgen, _stream, _utils, typed_attr
from ..backend.abc import AsyncBackend, TaskGroup
from ..backend.factory import current_async_backend
from ..transports import abc as transports, utils as transports_utils


class AsyncStreamClient(typed_attr.TypedAttributeProvider, Generic[_T_Response]):
    __slots__ = (
        "__transport",
        "__producer",
        "__send_guard",
        "__weakref__",
    )

    def __init__(
        self, transport: transports.AsyncStreamWriteTransport, producer: _stream.StreamDataProducer[_T_Response]
    ) -> None:
        super().__init__()

        self.__transport: transports.AsyncStreamWriteTransport = transport
        self.__producer: _stream.StreamDataProducer[_T_Response] = producer
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

    async def send_packet(self, packet: _T_Response) -> None:
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


class AsyncStreamServer(typed_attr.TypedAttributeProvider, Generic[_T_Request, _T_Response]):
    __slots__ = (
        "__listener",
        "__protocol",
        "__max_recv_size",
        "__serve_guard",
        "__weakref__",
    )

    def __init__(
        self,
        listener: transports.AsyncListener[transports.AsyncStreamTransport],
        protocol: protocol_module.StreamProtocol[_T_Response, _T_Request],
        max_recv_size: int,
    ) -> None:
        if not isinstance(listener, transports.AsyncListener):
            raise TypeError(f"Expected an AsyncListener object, got {listener!r}")
        if not isinstance(protocol, protocol_module.StreamProtocol):
            raise TypeError(f"Expected a StreamProtocol object, got {protocol!r}")
        if not isinstance(max_recv_size, int) or max_recv_size <= 0:
            raise ValueError("'max_recv_size' must be a strictly positive integer")

        self.__listener: transports.AsyncListener[transports.AsyncStreamTransport] = listener
        self.__protocol: protocol_module.StreamProtocol[_T_Response, _T_Request] = protocol
        self.__max_recv_size: int = max_recv_size
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
        client_connected_cb: Callable[[AsyncStreamClient[_T_Response]], AsyncGenerator[None, _T_Request]],
        task_group: TaskGroup | None = None,
    ) -> NoReturn:
        with self.__serve_guard:
            handler = _utils.prepend_argument(client_connected_cb, self.__client_coroutine)
            await self.__listener.serve(handler, task_group)

    async def __client_coroutine(
        self,
        client_connected_cb: Callable[[AsyncStreamClient[_T_Response]], AsyncGenerator[None, _T_Request]],
        transport: transports.AsyncStreamTransport,
    ) -> None:
        if not isinstance(transport, transports.AsyncStreamTransport):
            raise TypeError(f"Expected an AsyncStreamTransport object, got {transport!r}")

        async with contextlib.AsyncExitStack() as client_exit_stack:
            client_exit_stack.push_async_callback(transports_utils.aclose_forcefully, transport)

            producer = _stream.StreamDataProducer(self.__protocol)
            consumer: _stream.StreamDataConsumer[_T_Request] | _stream.BufferedStreamDataConsumer[_T_Request]

            request_receiver: _RequestReceiver[_T_Request] | _BufferedRequestReceiver[_T_Request]
            try:
                if not isinstance(transport, transports.AsyncBufferedStreamReadTransport):
                    raise UnsupportedOperation  # pragma: no cover
                consumer = _stream.BufferedStreamDataConsumer(self.__protocol, self.__max_recv_size)
                request_receiver = _BufferedRequestReceiver(
                    transport=transport,
                    consumer=consumer,
                    backend=current_async_backend(),
                )
            except UnsupportedOperation:
                consumer = _stream.StreamDataConsumer(self.__protocol)
                request_receiver = _RequestReceiver(
                    transport=transport,
                    consumer=consumer,
                    max_recv_size=self.__max_recv_size,
                    backend=current_async_backend(),
                )

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

                async for action in request_receiver:
                    try:
                        await action.asend(request_handler_generator)
                    except StopAsyncIteration:
                        break
                    finally:
                        del action

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__listener.extra_attributes


@dataclasses.dataclass(kw_only=True, eq=False, frozen=True, slots=True)
class _BaseRequestReceiver(Generic[_T_Request]):
    backend: AsyncBackend
    transport: transports.AsyncBaseTransport

    def _packet_iterator(self) -> Iterator[_T_Request]:  # pragma: no cover
        raise NotImplementedError

    async def _read_data_from_transport(self) -> bool:  # pragma: no cover
        raise NotImplementedError

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> _asyncgen.AsyncGenAction[None, _T_Request]:
        if self.transport.is_closing():
            raise StopAsyncIteration

        consumer = self._packet_iterator()
        try:
            while True:
                try:
                    request = next(consumer)
                except StopIteration:
                    pass
                else:
                    return _asyncgen.SendAction(request)
                if not await self._read_data_from_transport():
                    break
        except BaseException as exc:
            return _asyncgen.ThrowAction(exc)
        raise StopAsyncIteration


@dataclasses.dataclass(kw_only=True, eq=False, frozen=True, slots=True)
class _RequestReceiver(_BaseRequestReceiver[_T_Request]):
    transport: transports.AsyncStreamReadTransport
    consumer: _stream.StreamDataConsumer[_T_Request]
    max_recv_size: int

    def __post_init__(self) -> None:
        assert self.max_recv_size > 0, f"{self.max_recv_size=}"  # nosec assert_used

    def _packet_iterator(self) -> Iterator[_T_Request]:
        return self.consumer

    async def _read_data_from_transport(self) -> bool:
        data = await self.transport.recv(self.max_recv_size)
        if len(data):
            self.consumer.feed(data)
            return True
        return False  # Closed connection (EOF)


@dataclasses.dataclass(kw_only=True, eq=False, frozen=True, slots=True)
class _BufferedRequestReceiver(_BaseRequestReceiver[_T_Request]):
    transport: transports.AsyncBufferedStreamReadTransport
    consumer: _stream.BufferedStreamDataConsumer[_T_Request]

    def _packet_iterator(self) -> Iterator[_T_Request]:
        return self.consumer

    async def _read_data_from_transport(self) -> bool:
        nbytes: int = await self.transport.recv_into(self.consumer.get_write_buffer())
        if nbytes:
            self.consumer.buffer_updated(nbytes)
            return True
        return False  # Closed connection (EOF)
