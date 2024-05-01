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

__all__ = ["AsyncStreamClient", "AsyncStreamServer"]

import contextlib
import dataclasses
import warnings
from collections.abc import AsyncGenerator, Callable, Mapping
from typing import Any, Generic, Literal, NoReturn, assert_never

from .... import protocol as protocol_module
from ...._typevars import _T_Request, _T_Response
from ....exceptions import UnsupportedOperation
from ....warnings import ManualBufferAllocationWarning
from ... import _stream, _utils, typed_attr
from ..._asyncgen import AsyncGenAction, SendAction, ThrowAction
from ..backend.abc import AsyncBackend, TaskGroup
from ..transports import abc as transports, utils as transports_utils


class AsyncStreamClient(typed_attr.TypedAttributeProvider, Generic[_T_Response]):
    __slots__ = (
        "__transport",
        "__producer",
        "__exit_stack",
        "__send_guard",
        "__weakref__",
    )

    def __init__(
        self,
        transport: transports.AsyncStreamWriteTransport,
        producer: _stream.StreamDataProducer[_T_Response],
        exit_stack: contextlib.AsyncExitStack,
    ) -> None:
        super().__init__()

        self.__transport: transports.AsyncStreamWriteTransport = transport
        self.__producer: _stream.StreamDataProducer[_T_Response] = producer
        self.__exit_stack: contextlib.AsyncExitStack = exit_stack
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

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__transport.extra_attributes


class AsyncStreamServer(typed_attr.TypedAttributeProvider, Generic[_T_Request, _T_Response]):
    __slots__ = (
        "__listener",
        "__protocol",
        "__max_recv_size",
        "__serve_guard",
        "__manual_buffer_allocation",
        "__weakref__",
    )

    def __init__(
        self,
        listener: transports.AsyncListener[transports.AsyncStreamTransport],
        protocol: protocol_module.StreamProtocol[_T_Response, _T_Request],
        max_recv_size: int,
        *,
        manual_buffer_allocation: Literal["try", "no", "force"] = "try",
    ) -> None:
        if not isinstance(listener, transports.AsyncListener):
            raise TypeError(f"Expected an AsyncListener object, got {listener!r}")
        if not isinstance(protocol, protocol_module.StreamProtocol):
            raise TypeError(f"Expected a StreamProtocol object, got {protocol!r}")
        if not isinstance(max_recv_size, int) or max_recv_size <= 0:
            raise ValueError("'max_recv_size' must be a strictly positive integer")
        if manual_buffer_allocation not in ("try", "no", "force"):
            raise ValueError('"manual_buffer_allocation" must be "try", "no" or "force"')

        self.__listener: transports.AsyncListener[transports.AsyncStreamTransport] = listener
        self.__protocol: protocol_module.StreamProtocol[_T_Response, _T_Request] = protocol
        self.__max_recv_size: int = max_recv_size
        self.__serve_guard: _utils.ResourceGuard = _utils.ResourceGuard("another task is currently accepting new connections")
        self.__manual_buffer_allocation: Literal["try", "no", "force"] = manual_buffer_allocation

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

    @_utils.inherit_doc(transports.AsyncBaseTransport)
    def backend(self) -> AsyncBackend:
        return self.__listener.backend()

    async def serve(
        self,
        client_connected_cb: Callable[[AsyncStreamClient[_T_Response]], AsyncGenerator[float | None, _T_Request]],
        task_group: TaskGroup | None = None,
    ) -> NoReturn:
        with self.__serve_guard:
            handler = _utils.prepend_argument(client_connected_cb, self.__client_coroutine)
            await self.__listener.serve(handler, task_group)

    async def __client_coroutine(
        self,
        client_connected_cb: Callable[[AsyncStreamClient[_T_Response]], AsyncGenerator[float | None, _T_Request]],
        transport: transports.AsyncStreamTransport,
    ) -> None:
        if not isinstance(transport, transports.AsyncStreamTransport):
            raise TypeError(f"Expected an AsyncStreamTransport object, got {transport!r}")

        async with contextlib.AsyncExitStack() as task_exit_stack:
            task_exit_stack.push_async_callback(transports_utils.aclose_forcefully, transport)

            producer = _stream.StreamDataProducer(self.__protocol)
            consumer: _stream.StreamDataConsumer[_T_Request] | _stream.BufferedStreamDataConsumer[_T_Request]

            request_receiver: _RequestReceiver[_T_Request] | _BufferedRequestReceiver[_T_Request]
            match self.__manual_buffer_allocation:
                case "try" | "force" as manual_buffer_allocation:
                    try:
                        consumer = _stream.BufferedStreamDataConsumer(self.__protocol, self.__max_recv_size)
                        if not isinstance(transport, transports.AsyncBufferedStreamReadTransport):
                            msg = f"The transport implementation {transport!r} does not implement AsyncBufferedStreamReadTransport interface"
                            if manual_buffer_allocation == "try":
                                warnings.warn(
                                    f'{msg}. Consider explicitly setting the "manual_buffer_allocation" strategy to "no".',
                                    category=ManualBufferAllocationWarning,
                                    stacklevel=1,
                                )
                            raise UnsupportedOperation(msg)
                        request_receiver = _BufferedRequestReceiver(
                            transport=transport,
                            consumer=consumer,
                        )
                    except UnsupportedOperation as exc:
                        if manual_buffer_allocation == "force":
                            exc.add_note('Consider setting the "manual_buffer_allocation" strategy to "no"')
                            raise
                        consumer = _stream.StreamDataConsumer(self.__protocol)
                        request_receiver = _RequestReceiver(
                            transport=transport,
                            consumer=consumer,
                            max_recv_size=self.__max_recv_size,
                        )
                case "no":
                    consumer = _stream.StreamDataConsumer(self.__protocol)
                    request_receiver = _RequestReceiver(
                        transport=transport,
                        consumer=consumer,
                        max_recv_size=self.__max_recv_size,
                    )
                case manual_buffer_allocation:  # pragma: no cover
                    assert_never(manual_buffer_allocation)

            client_exit_stack = await task_exit_stack.enter_async_context(contextlib.AsyncExitStack())
            client_exit_stack.callback(consumer.clear)

            client = AsyncStreamClient(transport, producer, client_exit_stack)

            request_handler_generator = client_connected_cb(client)

            del client_exit_stack, task_exit_stack, client_connected_cb, client

            timeout: float | None
            try:
                timeout = await anext(request_handler_generator)
            except StopAsyncIteration:
                return
            else:
                while True:
                    try:
                        action = await request_receiver.next(timeout)
                    except StopAsyncIteration:
                        break
                    try:
                        timeout = await action.asend(request_handler_generator)
                    except StopAsyncIteration:
                        break
                    finally:
                        del action
            finally:
                await request_handler_generator.aclose()

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__listener.extra_attributes


@dataclasses.dataclass(kw_only=True, eq=False, frozen=True, slots=True)
class _RequestReceiver(Generic[_T_Request]):
    transport: transports.AsyncStreamReadTransport
    consumer: _stream.StreamDataConsumer[_T_Request]
    max_recv_size: int
    __null_timeout_ctx: contextlib.nullcontext[None] = dataclasses.field(init=False, default_factory=contextlib.nullcontext)

    def __post_init__(self) -> None:
        assert self.max_recv_size > 0, f"{self.max_recv_size=}"  # nosec assert_used

    async def next(self, timeout: float | None) -> AsyncGenAction[_T_Request]:
        try:
            consumer = self.consumer
            try:
                request = consumer.next(None)
            except StopIteration:
                pass
            else:
                return SendAction(request)

            with self.__null_timeout_ctx if timeout is None else self.transport.backend().timeout(timeout):
                while data := await self.transport.recv(self.max_recv_size):
                    try:
                        request = consumer.next(data)
                    except StopIteration:
                        continue
                    finally:
                        del data
                    return SendAction(request)
        except BaseException as exc:
            return ThrowAction(exc)
        raise StopAsyncIteration


@dataclasses.dataclass(kw_only=True, eq=False, frozen=True, slots=True)
class _BufferedRequestReceiver(Generic[_T_Request]):
    transport: transports.AsyncBufferedStreamReadTransport
    consumer: _stream.BufferedStreamDataConsumer[_T_Request]
    __null_timeout_ctx: contextlib.nullcontext[None] = dataclasses.field(init=False, default_factory=contextlib.nullcontext)

    async def next(self, timeout: float | None) -> AsyncGenAction[_T_Request]:
        try:
            consumer = self.consumer
            try:
                request = consumer.next(None)
            except StopIteration:
                pass
            else:
                return SendAction(request)

            with self.__null_timeout_ctx if timeout is None else self.transport.backend().timeout(timeout):
                while nbytes := await self.transport.recv_into(consumer.get_write_buffer()):
                    try:
                        request = consumer.next(nbytes)
                    except StopIteration:
                        continue
                    return SendAction(request)
        except BaseException as exc:
            return ThrowAction(exc)
        raise StopAsyncIteration
