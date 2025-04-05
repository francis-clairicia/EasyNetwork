# Copyright 2021-2025, Francis Clairicia-Rose-Claire-Josephine
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
"""Low-level asynchronous stream servers module."""

from __future__ import annotations

__all__ = ["AsyncStreamServer", "ConnectedStreamClient"]

import contextlib
import dataclasses
import functools
import logging
import math
import types
import warnings
from collections.abc import AsyncGenerator, Callable, Mapping
from typing import Any, Generic, NoReturn, assert_never

from ...._typevars import _T_Request, _T_Response
from ....protocol import AnyStreamProtocolType
from ... import _stream, _utils
from ..backend.abc import AsyncBackend, TaskGroup
from ..transports import abc as _transports, utils as _transports_utils


class ConnectedStreamClient(_transports.AsyncBaseTransport, Generic[_T_Response]):
    """
    Write-end of the connected client.
    """

    __slots__ = (
        "__transport",
        "__producer",
        "__send_guard",
    )

    def __init__(
        self,
        *,
        _transport: _transports.AsyncStreamWriteTransport,
        _producer: _stream.StreamDataProducer[_T_Response],
    ) -> None:
        super().__init__()

        self.__transport: _transports.AsyncStreamWriteTransport = _transport
        self.__producer: _stream.StreamDataProducer[_T_Response] = _producer
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

        Warning:
            :meth:`aclose` performs a graceful close, waiting for the transport to close.

            If :meth:`aclose` is cancelled, the transport is closed abruptly.
        """
        with self.__send_guard:
            await self.__transport.aclose()

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

    @_utils.inherit_doc(_transports.AsyncBaseTransport)
    def backend(self) -> AsyncBackend:
        return self.__transport.backend()

    @property
    @_utils.inherit_doc(_transports.AsyncBaseTransport)
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__transport.extra_attributes


class AsyncStreamServer(_transports.AsyncBaseTransport, Generic[_T_Request, _T_Response]):
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
        listener: _transports.AsyncListener[_transports.AsyncStreamTransport],
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

        if not isinstance(listener, _transports.AsyncListener):
            raise TypeError(f"Expected an AsyncListener object, got {listener!r}")

        _check_any_protocol(protocol)

        if not isinstance(max_recv_size, int) or max_recv_size <= 0:
            raise ValueError("'max_recv_size' must be a strictly positive integer")

        self.__listener: _transports.AsyncListener[_transports.AsyncStreamTransport] = listener
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

    @_utils.inherit_doc(_transports.AsyncBaseTransport)
    def backend(self) -> AsyncBackend:
        return self.__listener.backend()

    async def serve(
        self,
        client_connected_cb: Callable[[ConnectedStreamClient[_T_Response]], AsyncGenerator[float | None, _T_Request]],
        task_group: TaskGroup | None = None,
        *,
        disconnect_error_filter: Callable[[Exception], bool] | None = None,
    ) -> NoReturn:
        """
        Accept incoming connections as they come in and start tasks to handle them.

        Parameters:
            client_connected_cb: a callable that will be used to handle each accepted connection.
            task_group: the task group that will be used to start tasks for handling each accepted connection.
            disconnect_error_filter: a callable that returns :data:`True` if the exception is the result of a pipe disconnect.
        """
        with self.__serve_guard:
            handler = functools.partial(self.__client_coroutine, client_connected_cb, disconnect_error_filter)
            await self.__listener.serve(handler, task_group)

    async def __client_coroutine(
        self,
        client_connected_cb: Callable[[ConnectedStreamClient[_T_Response]], AsyncGenerator[float | None, _T_Request]],
        disconnect_error_filter: Callable[[Exception], bool] | None,
        transport: _transports.AsyncStreamTransport,
    ) -> None:
        if not isinstance(transport, _transports.AsyncStreamTransport):
            raise TypeError(f"Expected an AsyncStreamTransport object, got {transport!r}")

        from ....protocol import BufferedStreamProtocol, StreamProtocol

        async with contextlib.AsyncExitStack() as task_exit_stack:
            task_exit_stack.push(self.__unhandled_exception_log)

            # By default, abort the connection at the end of the task.
            transport_close_exit_stack = await task_exit_stack.enter_async_context(contextlib.AsyncExitStack())
            transport_close_exit_stack.push_async_callback(_transports_utils.aclose_forcefully, transport)

            producer = _stream.StreamDataProducer(self.__protocol)
            consumer: _stream.StreamDataConsumer[_T_Request] | _stream.BufferedStreamDataConsumer[_T_Request]

            request_receiver: _RequestReceiver[_T_Request] | _BufferedRequestReceiver[_T_Request]
            match self.__protocol:
                case BufferedStreamProtocol():
                    consumer = _stream.BufferedStreamDataConsumer(self.__protocol, self.__max_recv_size)
                    request_receiver = _BufferedRequestReceiver(
                        transport=transport,
                        consumer=consumer,
                        disconnect_error_filter=disconnect_error_filter,
                    )
                case StreamProtocol():
                    consumer = _stream.StreamDataConsumer(self.__protocol)
                    request_receiver = _RequestReceiver(
                        transport=transport,
                        consumer=consumer,
                        max_recv_size=self.__max_recv_size,
                        disconnect_error_filter=disconnect_error_filter,
                    )
                case _:  # pragma: no cover
                    assert_never(self.__protocol)

            # NOTE: It is safe to clear the consumer before the transport here.
            #       There is no task reading the transport at this point.
            task_exit_stack.callback(consumer.clear)

            request_handler_generator = client_connected_cb(
                ConnectedStreamClient(
                    _transport=transport,
                    _producer=producer,
                )
            )

            timeout: float | None
            try:
                timeout = await anext(request_handler_generator)
            except StopAsyncIteration:
                return
            else:
                try:
                    request: _T_Request | None
                    _timeout_scope_ctx = self.backend().timeout
                    _validate_timeout_delay = _utils.validate_optional_timeout_delay
                    _transport_is_closing = transport.is_closing
                    _next_packet = request_receiver.next
                    _request_handler_generator_asend = request_handler_generator.asend
                    while not _transport_is_closing():
                        try:
                            match _validate_timeout_delay(timeout, positive_check=True):
                                case math.inf:
                                    request = await _next_packet()
                                case timeout:
                                    with _timeout_scope_ctx(timeout):
                                        request = await _next_packet()
                        except StopAsyncIteration:
                            raise
                        except BaseException as exc:
                            timeout = await request_handler_generator.athrow(exc)
                        else:
                            timeout = await _request_handler_generator_asend(request)
                        finally:
                            request = None
                except StopAsyncIteration:
                    # Request handler stopped normally, attempt a graceful close.
                    transport_close_exit_stack.pop_all()
                    transport_close_exit_stack.push_async_exit(contextlib.aclosing(transport))
                    return
            finally:
                await request_handler_generator.aclose()

    @classmethod
    def __unhandled_exception_log(
        cls,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
        /,
    ) -> bool:
        if exc_type is not None and issubclass(exc_type, Exception):
            logger = logging.getLogger(__name__)
            logger.error("Unhandled exception: %s", exc_val, exc_info=(exc_type, exc_val or exc_type(), exc_tb))
            return True
        return False

    @property
    @_utils.inherit_doc(_transports.AsyncBaseTransport)
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__listener.extra_attributes


@dataclasses.dataclass(kw_only=True, eq=False, slots=True)
class _RequestReceiver(Generic[_T_Request]):
    transport: _transports.AsyncStreamReadTransport
    consumer: _stream.StreamDataConsumer[_T_Request]
    max_recv_size: int
    disconnect_error_filter: Callable[[Exception], bool] | None
    __backend: AsyncBackend = dataclasses.field(init=False)

    def __post_init__(self) -> None:
        assert self.max_recv_size > 0, f"{self.max_recv_size=}"  # nosec assert_used
        self.__backend = self.transport.backend()

    async def next(self) -> _T_Request:
        consumer = self.consumer
        try:
            request = consumer.next(None)
        except StopIteration:
            pass
        else:
            await self.__backend.cancel_shielded_coro_yield()
            return request

        data: bytes
        while True:
            try:
                data = await self.transport.recv(self.max_recv_size)
            except Exception as exc:
                if self.disconnect_error_filter is not None and self.disconnect_error_filter(exc):
                    break
                raise

            if not data:
                break
            try:
                return consumer.next(data)
            except StopIteration:
                pass
            finally:
                del data

        raise StopAsyncIteration


@dataclasses.dataclass(kw_only=True, eq=False, slots=True)
class _BufferedRequestReceiver(Generic[_T_Request]):
    transport: _transports.AsyncStreamReadTransport
    consumer: _stream.BufferedStreamDataConsumer[_T_Request]
    disconnect_error_filter: Callable[[Exception], bool] | None
    __backend: AsyncBackend = dataclasses.field(init=False)

    def __post_init__(self) -> None:
        self.__backend = self.transport.backend()

    async def next(self) -> _T_Request:
        consumer = self.consumer
        try:
            request = consumer.next(None)
        except StopIteration:
            pass
        else:
            await self.__backend.cancel_shielded_coro_yield()
            return request

        nbytes: int
        while True:
            with consumer.get_write_buffer() as buffer:
                try:
                    nbytes = await self.transport.recv_into(buffer)
                except Exception as exc:
                    if self.disconnect_error_filter is not None and self.disconnect_error_filter(exc):
                        break
                    raise
            if not nbytes:
                break
            try:
                return consumer.next(nbytes)
            except StopIteration:
                pass

        raise StopAsyncIteration
