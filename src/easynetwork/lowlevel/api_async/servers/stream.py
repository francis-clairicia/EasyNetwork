# Copyright 2021-2024, Francis Clairicia-Rose-Claire-Josephine
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

__all__ = ["AsyncStreamServer"]

import contextlib
import dataclasses
import warnings
from collections.abc import AsyncGenerator, Callable, Mapping
from typing import Any, Generic, NoReturn, assert_never

from ...._typevars import _T_Request, _T_Response
from ....protocol import AnyStreamProtocolType
from ... import _stream, _utils
from ..._asyncgen import AsyncGenAction, SendAction, ThrowAction
from ..backend.abc import AsyncBackend, TaskGroup
from ..transports import utils as transports_utils
from ..transports.abc import (
    AsyncBaseTransport,
    AsyncListener,
    AsyncStreamReadTransport,
    AsyncStreamTransport,
    AsyncStreamWriteTransport,
)


class Client(AsyncBaseTransport, Generic[_T_Response]):
    """
    Write-end of the connected client.
    """

    __slots__ = (
        "__transport",
        "__producer",
        "__exit_stack",
        "__send_guard",
    )

    def __init__(
        self,
        *,
        _transport: AsyncStreamWriteTransport,
        _producer: _stream.StreamDataProducer[_T_Response],
        _exit_stack: contextlib.AsyncExitStack,
    ) -> None:
        super().__init__()

        self.__transport: AsyncStreamWriteTransport = _transport
        self.__producer: _stream.StreamDataProducer[_T_Response] = _producer
        self.__exit_stack: contextlib.AsyncExitStack = _exit_stack
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
        await self.__exit_stack.aclose()

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
            await self.__transport.send_all_from_iterable(self.__producer.generate(packet))

    @_utils.inherit_doc(AsyncBaseTransport)
    def backend(self) -> AsyncBackend:
        return self.__transport.backend()

    @property
    @_utils.inherit_doc(AsyncBaseTransport)
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__transport.extra_attributes


class AsyncStreamServer(AsyncBaseTransport, Generic[_T_Request, _T_Response]):
    """
    Stream listener interface.
    """

    __slots__ = (
        "__listener",
        "__protocol",
        "__max_recv_size",
        "__serve_guard",
    )

    def __init__(
        self,
        listener: AsyncListener[AsyncStreamTransport],
        protocol: AnyStreamProtocolType[_T_Response, _T_Request],
        max_recv_size: int,
    ) -> None:
        """
        Parameters:
            listener: the transport implementation to wrap.
            protocol: The :term:`protocol object` to use.
            max_recv_size: Read buffer size.
        """
        from ....lowlevel._stream import _check_any_protocol

        if not isinstance(listener, AsyncListener):
            raise TypeError(f"Expected an AsyncListener object, got {listener!r}")

        _check_any_protocol(protocol)

        if not isinstance(max_recv_size, int) or max_recv_size <= 0:
            raise ValueError("'max_recv_size' must be a strictly positive integer")

        self.__listener: AsyncListener[AsyncStreamTransport] = listener
        self.__protocol: AnyStreamProtocolType[_T_Response, _T_Request] = protocol
        self.__max_recv_size: int = max_recv_size
        self.__serve_guard: _utils.ResourceGuard = _utils.ResourceGuard("another task is currently accepting new connections")

    def __del__(self, *, _warn: _utils.WarnCallback = warnings.warn) -> None:
        try:
            listener = self.__listener
        except AttributeError:
            return
        if not listener.is_closing():
            msg = f"unclosed server {self!r} pointing to {listener!r} (and cannot be closed synchronously)"
            _warn(msg, ResourceWarning, source=self)

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

    @_utils.inherit_doc(AsyncBaseTransport)
    def backend(self) -> AsyncBackend:
        return self.__listener.backend()

    async def serve(
        self,
        client_connected_cb: Callable[[Client[_T_Response]], AsyncGenerator[float | None, _T_Request]],
        task_group: TaskGroup | None = None,
    ) -> NoReturn:
        """
        Accept incoming connections as they come in and start tasks to handle them.

        Parameters:
            client_connected_cb: a callable that will be used to handle each accepted connection.
            task_group: the task group that will be used to start tasks for handling each accepted connection.
        """
        with self.__serve_guard:
            handler = _utils.prepend_argument(client_connected_cb, self.__client_coroutine)
            await self.__listener.serve(handler, task_group)

    async def __client_coroutine(
        self,
        client_connected_cb: Callable[[Client[_T_Response]], AsyncGenerator[float | None, _T_Request]],
        transport: AsyncStreamTransport,
    ) -> None:
        if not isinstance(transport, AsyncStreamTransport):
            raise TypeError(f"Expected an AsyncStreamTransport object, got {transport!r}")

        from ....protocol import BufferedStreamProtocol, StreamProtocol

        async with contextlib.AsyncExitStack() as task_exit_stack:
            task_exit_stack.push_async_callback(transports_utils.aclose_forcefully, transport)

            producer = _stream.StreamDataProducer(self.__protocol)
            consumer: _stream.StreamDataConsumer[_T_Request] | _stream.BufferedStreamDataConsumer[_T_Request]

            request_receiver: _RequestReceiver[_T_Request] | _BufferedRequestReceiver[_T_Request]
            match self.__protocol:
                case BufferedStreamProtocol():
                    consumer = _stream.BufferedStreamDataConsumer(self.__protocol, self.__max_recv_size)
                    request_receiver = _BufferedRequestReceiver(
                        transport=transport,
                        consumer=consumer,
                    )
                case StreamProtocol():
                    consumer = _stream.StreamDataConsumer(self.__protocol)
                    request_receiver = _RequestReceiver(
                        transport=transport,
                        consumer=consumer,
                        max_recv_size=self.__max_recv_size,
                    )
                case _:  # pragma: no cover
                    assert_never(self.__protocol)

            client_exit_stack = await task_exit_stack.enter_async_context(contextlib.AsyncExitStack())
            client_exit_stack.callback(consumer.clear)

            request_handler_generator = client_connected_cb(
                Client(
                    _transport=transport,
                    _producer=producer,
                    _exit_stack=client_exit_stack,
                )
            )

            timeout: float | None
            try:
                timeout = await anext(request_handler_generator)
            except StopAsyncIteration:
                return
            else:
                try:
                    action: AsyncGenAction[_T_Request] | None
                    while True:
                        action = await request_receiver.next(timeout)
                        try:
                            timeout = await action.asend(request_handler_generator)
                        finally:
                            action = None
                except StopAsyncIteration:
                    return
            finally:
                await request_handler_generator.aclose()

    @property
    @_utils.inherit_doc(AsyncBaseTransport)
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__listener.extra_attributes


@dataclasses.dataclass(kw_only=True, eq=False, slots=True)
class _RequestReceiver(Generic[_T_Request]):
    transport: AsyncStreamReadTransport
    consumer: _stream.StreamDataConsumer[_T_Request]
    max_recv_size: int
    __null_timeout_ctx: contextlib.nullcontext[None] = dataclasses.field(init=False, default_factory=contextlib.nullcontext)
    __backend: AsyncBackend = dataclasses.field(init=False)

    def __post_init__(self) -> None:
        assert self.max_recv_size > 0, f"{self.max_recv_size=}"  # nosec assert_used
        self.__backend = self.transport.backend()

    async def next(self, timeout: float | None) -> AsyncGenAction[_T_Request]:
        try:
            consumer = self.consumer
            with self.__null_timeout_ctx if timeout is None else self.__backend.timeout(timeout):
                data: bytes | None = None
                while True:
                    try:
                        request = consumer.next(data)
                    except StopIteration:
                        pass
                    else:
                        return SendAction(request)
                    finally:
                        data = None
                    data = await self.transport.recv(self.max_recv_size)
                    if not data:
                        break
        except BaseException as exc:
            return ThrowAction(exc)
        raise StopAsyncIteration


@dataclasses.dataclass(kw_only=True, eq=False, slots=True)
class _BufferedRequestReceiver(Generic[_T_Request]):
    transport: AsyncStreamReadTransport
    consumer: _stream.BufferedStreamDataConsumer[_T_Request]
    __null_timeout_ctx: contextlib.nullcontext[None] = dataclasses.field(init=False, default_factory=contextlib.nullcontext)
    __backend: AsyncBackend = dataclasses.field(init=False)

    def __post_init__(self) -> None:
        self.__backend = self.transport.backend()

    async def next(self, timeout: float | None) -> AsyncGenAction[_T_Request]:
        try:
            consumer = self.consumer
            with self.__null_timeout_ctx if timeout is None else self.__backend.timeout(timeout):
                nbytes: int | None = None
                while True:
                    try:
                        request = consumer.next(nbytes)
                    except StopIteration:
                        pass
                    else:
                        return SendAction(request)
                    nbytes = await self.transport.recv_into(consumer.get_write_buffer())
                    if not nbytes:
                        break
        except BaseException as exc:
            return ThrowAction(exc)
        raise StopAsyncIteration
