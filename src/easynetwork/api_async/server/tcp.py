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
"""Asynchronous network server module"""

from __future__ import annotations

__all__ = ["AsyncTCPNetworkServer"]

import contextlib as _contextlib
import errno as _errno
import inspect
import logging
import os
import weakref
from collections import deque
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Coroutine, Iterator, Mapping, Sequence
from typing import TYPE_CHECKING, Any, Generic, final

from ..._typevars import _RequestT, _ResponseT
from ...exceptions import ClientClosedError, ServerAlreadyRunning, ServerClosedError
from ...protocol import StreamProtocol
from ...tools._stream import StreamDataConsumer, StreamDataProducer
from ...tools._utils import (
    check_real_socket_state as _check_real_socket_state,
    make_callback as _make_callback,
    remove_traceback_frames_in_place as _remove_traceback_frames_in_place,
)
from ...tools.constants import (
    ACCEPT_CAPACITY_ERRNOS,
    ACCEPT_CAPACITY_ERROR_SLEEP_TIME,
    MAX_STREAM_BUFSIZE,
    SSL_HANDSHAKE_TIMEOUT,
    SSL_SHUTDOWN_TIMEOUT,
)
from ...tools.socket import (
    ISocket,
    SocketAddress,
    SocketProxy,
    enable_socket_linger,
    new_socket_address,
    set_tcp_keepalive,
    set_tcp_nodelay,
)
from ..backend.factory import AsyncBackendFactory
from ..backend.tasks import SingleTaskRunner
from ._tools.actions import ErrorAction as _ErrorAction, RequestAction as _RequestAction
from .abc import AbstractAsyncNetworkServer, SupportsEventSet
from .handler import AsyncStreamClient, AsyncStreamRequestHandler

if TYPE_CHECKING:
    from ssl import SSLContext as _SSLContext

    from ..backend.abc import (
        AcceptedSocket,
        AsyncBackend,
        AsyncListenerSocketAdapter,
        AsyncStreamSocketAdapter,
        IEvent,
        Task,
        TaskGroup,
    )


class AsyncTCPNetworkServer(AbstractAsyncNetworkServer, Generic[_RequestT, _ResponseT]):
    """
    An asynchronous network server for TCP connections.
    """

    __slots__ = (
        "__backend",
        "__listeners",
        "__listeners_factory",
        "__listeners_factory_runner",
        "__protocol",
        "__request_handler",
        "__is_shutdown",
        "__shutdown_asked",
        "__max_recv_size",
        "__listener_tasks",
        "__mainloop_task",
        "__client_connection_log_level",
        "__logger",
    )

    def __init__(
        self,
        host: str | None | Sequence[str],
        port: int,
        protocol: StreamProtocol[_ResponseT, _RequestT],
        request_handler: AsyncStreamRequestHandler[_RequestT, _ResponseT],
        *,
        ssl: _SSLContext | None = None,
        ssl_handshake_timeout: float | None = None,
        ssl_shutdown_timeout: float | None = None,
        backlog: int | None = None,
        reuse_port: bool = False,
        max_recv_size: int | None = None,
        log_client_connection: bool | None = None,
        logger: logging.Logger | None = None,
        backend: str | AsyncBackend | None = None,
        backend_kwargs: Mapping[str, Any] | None = None,
    ) -> None:
        """
        Parameters:
            host: Can be set to several types which determine where the server would be listening:

                  * If `host` is a string, the TCP server is bound to a single network interface specified by `host`.

                  * If `host` is a sequence of strings, the TCP server is bound to all network interfaces specified by the sequence.

                  * If `host` is :data:`None`, all interfaces are assumed and a list of multiple sockets will be returned
                    (most likely one for IPv4 and another one for IPv6).
            port: specify which port the server should listen on. If the value is ``0``, a random unused port will be selected
                  (note that if `host` resolves to multiple network interfaces, a different random port will be selected
                  for each interface).
            protocol: The :term:`protocol object` to use.
            request_handler: The request handler to use.

        Keyword Arguments:
            ssl: can be set to an :class:`ssl.SSLContext` instance to enable TLS over the accepted connections.
            ssl_handshake_timeout: (for a TLS connection) the time in seconds to wait for the TLS handshake to complete
                                   before aborting the connection. ``60.0`` seconds if :data:`None` (default).
            ssl_shutdown_timeout: the time in seconds to wait for the SSL shutdown to complete before aborting the connection.
                                  ``30.0`` seconds if :data:`None` (default).
            backlog: is the maximum number of queued connections passed to :class:`~socket.socket.listen` (defaults to ``100``).
            reuse_port: tells the kernel to allow this endpoint to be bound to the same port as other existing endpoints
                        are bound to, so long as they all set this flag when being created.
                        This option is not supported on Windows.
            max_recv_size: Read buffer size. If not given, a default reasonable value is used.
            log_client_connection: If :data:`True`, log clients connection/disconnection in :data:`logging.INFO` level.
                                   (This log will always be available in :data:`logging.DEBUG` level.)
            logger: If given, the logger instance to use.

        Backend Parameters:
            backend: the backend to use. Automatically determined otherwise.
            backend_kwargs: Keyword arguments for backend instanciation.
                            Ignored if `backend` is already an :class:`.AsyncBackend` instance.

        See Also:
            :ref:`SSL/TLS security considerations <ssl-security>`
        """
        super().__init__()

        if not isinstance(protocol, StreamProtocol):
            raise TypeError(f"Expected a StreamProtocol object, got {protocol!r}")
        if not isinstance(request_handler, AsyncStreamRequestHandler):
            raise TypeError(f"Expected an AsyncStreamRequestHandler object, got {request_handler!r}")

        backend = AsyncBackendFactory.ensure(backend, backend_kwargs)

        if backlog is None:
            backlog = 100

        if log_client_connection is None:
            log_client_connection = True

        if max_recv_size is None:
            max_recv_size = MAX_STREAM_BUFSIZE
        if not isinstance(max_recv_size, int) or max_recv_size <= 0:
            raise ValueError("'max_recv_size' must be a strictly positive integer")

        if ssl_handshake_timeout is not None and not ssl:
            raise ValueError("ssl_handshake_timeout is only meaningful with ssl")

        if ssl_shutdown_timeout is not None and not ssl:
            raise ValueError("ssl_shutdown_timeout is only meaningful with ssl")

        def _value_or_default(value: float | None, default: float) -> float:
            return value if value is not None else default

        self.__listeners_factory: Callable[[], Coroutine[Any, Any, Sequence[AsyncListenerSocketAdapter]]] | None
        if ssl:
            self.__listeners_factory = _make_callback(
                backend.create_ssl_over_tcp_listeners,
                host,
                port,
                backlog=backlog,
                ssl_context=ssl,
                ssl_handshake_timeout=_value_or_default(ssl_handshake_timeout, SSL_HANDSHAKE_TIMEOUT),
                ssl_shutdown_timeout=_value_or_default(ssl_shutdown_timeout, SSL_SHUTDOWN_TIMEOUT),
                reuse_port=reuse_port,
            )
        else:
            self.__listeners_factory = _make_callback(
                backend.create_tcp_listeners,
                host,
                port,
                backlog=backlog,
                reuse_port=reuse_port,
            )
        self.__listeners_factory_runner: SingleTaskRunner[Sequence[AsyncListenerSocketAdapter]] | None = None

        self.__backend: AsyncBackend = backend
        self.__listeners: tuple[AsyncListenerSocketAdapter, ...] | None = None
        self.__protocol: StreamProtocol[_ResponseT, _RequestT] = protocol
        self.__request_handler: AsyncStreamRequestHandler[_RequestT, _ResponseT] = request_handler
        self.__is_shutdown: IEvent = self.__backend.create_event()
        self.__is_shutdown.set()
        self.__shutdown_asked: bool = False
        self.__max_recv_size: int = max_recv_size
        self.__listener_tasks: deque[Task[None]] = deque()
        self.__mainloop_task: Task[None] | None = None
        self.__logger: logging.Logger = logger or logging.getLogger(__name__)
        self.__client_connection_log_level: int
        if log_client_connection:
            self.__client_connection_log_level = logging.INFO
        else:
            self.__client_connection_log_level = logging.DEBUG

    def is_serving(self) -> bool:
        return self.__listeners is not None and all(not listener.is_closing() for listener in self.__listeners)

    is_serving.__doc__ = AbstractAsyncNetworkServer.is_serving.__doc__

    def stop_listening(self) -> None:
        """
        Schedules the shutdown of all listener sockets.

        After that, all new connections will be refused, but the server will continue to run and handle
        previously accepted connections.

        Further calls to :meth:`is_serving` will return :data:`False`.
        """
        with _contextlib.ExitStack() as exit_stack:
            for listener_task in self.__listener_tasks:
                exit_stack.callback(listener_task.cancel)
                del listener_task

    async def server_close(self) -> None:
        self.__kill_listener_factory_runner()
        self.__listeners_factory = None
        await self.__close_listeners()

    server_close.__doc__ = AbstractAsyncNetworkServer.server_close.__doc__

    async def __close_listeners(self) -> None:
        async with _contextlib.AsyncExitStack() as exit_stack:
            listeners, self.__listeners = self.__listeners, None
            if listeners is not None:

                async def close_listener(listener: AsyncListenerSocketAdapter) -> None:
                    with _contextlib.suppress(OSError):
                        await listener.aclose()

                for listener in listeners:
                    exit_stack.push_async_callback(close_listener, listener)
                    del listener

            for listener_task in self.__listener_tasks:
                listener_task.cancel()
                exit_stack.push_async_callback(listener_task.wait)
                del listener_task

            await self.__backend.cancel_shielded_coro_yield()

    async def shutdown(self) -> None:
        self.__kill_listener_factory_runner()
        if self.__mainloop_task is not None:
            self.__mainloop_task.cancel()
        if self.__shutdown_asked:
            await self.__is_shutdown.wait()
            return
        self.__shutdown_asked = True
        try:
            await self.__is_shutdown.wait()
        finally:
            self.__shutdown_asked = False

    shutdown.__doc__ = AbstractAsyncNetworkServer.shutdown.__doc__

    def __kill_listener_factory_runner(self) -> None:
        if self.__listeners_factory_runner is not None:
            self.__listeners_factory_runner.cancel()

    async def serve_forever(self, *, is_up_event: SupportsEventSet | None = None) -> None:
        async with _contextlib.AsyncExitStack() as server_exit_stack:
            is_up_callback = server_exit_stack.enter_context(_contextlib.ExitStack())
            if is_up_event is not None:
                # Force is_up_event to be set, in order not to stuck the waiting task
                is_up_callback.callback(is_up_event.set)

            # Wake up server
            if not self.__is_shutdown.is_set():
                raise ServerAlreadyRunning("Server is already running")
            self.__is_shutdown = is_shutdown = self.__backend.create_event()
            server_exit_stack.callback(is_shutdown.set)
            ################

            # Bind and activate
            assert self.__listeners is None  # nosec assert_used
            assert self.__listeners_factory_runner is None  # nosec assert_used
            if self.__listeners_factory is None:
                raise ServerClosedError("Closed server")
            try:
                self.__listeners_factory_runner = SingleTaskRunner(self.__backend, self.__listeners_factory)
                self.__listeners = tuple(await self.__listeners_factory_runner.run())
            finally:
                self.__listeners_factory_runner = None
            if not self.__listeners:
                self.__listeners = None
                raise OSError("empty listeners list")
            ###################

            # Final teardown
            server_exit_stack.callback(self.__logger.info, "Server stopped")
            server_exit_stack.push_async_callback(lambda: self.__backend.ignore_cancellation(self.__close_listeners()))
            ################

            # Initialize request handler
            await self.__request_handler.service_init(
                await server_exit_stack.enter_async_context(_contextlib.AsyncExitStack()),
                weakref.proxy(self),
            )
            ############################

            # Setup task group
            server_exit_stack.callback(self.__listener_tasks.clear)
            task_group = await server_exit_stack.enter_async_context(self.__backend.create_task_group())
            server_exit_stack.callback(self.__logger.info, "Server loop break, waiting for remaining tasks...")
            ##################

            # Enable listener
            self.__listener_tasks.extend(
                task_group.start_soon(self.__listener_accept, listener, task_group) for listener in self.__listeners
            )
            self.__logger.info("Start serving at %s", ", ".join(map(str, self.get_addresses())))
            #################

            # Server is up
            is_up_callback.close()
            del is_up_callback
            ##############

            # Main loop
            self.__mainloop_task = task_group.start_soon(self.__backend.sleep_forever)
            if self.__shutdown_asked:
                self.__mainloop_task.cancel()
            try:
                await self.__mainloop_task.join()
            finally:
                self.__mainloop_task = None

    serve_forever.__doc__ = AbstractAsyncNetworkServer.serve_forever.__doc__

    async def __listener_accept(self, listener: AsyncListenerSocketAdapter, task_group: TaskGroup) -> None:
        backend = self.__backend
        client_task = self.__client_coroutine
        async with listener:
            while True:
                try:
                    client_socket: AcceptedSocket = await listener.accept()
                except OSError as exc:  # pragma: no cover  # Not testable
                    if exc.errno in ACCEPT_CAPACITY_ERRNOS:
                        self.__logger.error(
                            "accept returned %s (%s); retrying in %s seconds",
                            _errno.errorcode[exc.errno],
                            os.strerror(exc.errno),
                            ACCEPT_CAPACITY_ERROR_SLEEP_TIME,
                            exc_info=True,
                        )
                        await backend.sleep(ACCEPT_CAPACITY_ERROR_SLEEP_TIME)
                    else:
                        raise
                else:
                    task_group.start_soon(client_task, client_socket)
                    del client_socket
                    await backend.coro_yield()

    async def __client_coroutine(self, accepted_socket: AcceptedSocket) -> None:
        async with _contextlib.AsyncExitStack() as client_exit_stack:
            client_exit_stack.enter_context(self.__suppress_and_log_remaining_exception())

            try:
                socket: AsyncStreamSocketAdapter = await accepted_socket.connect()
            finally:
                del accepted_socket

            client_exit_stack.push_async_callback(self.__force_close_stream_socket, socket)

            # If the socket was not closed gracefully, (i.e. client.aclose() failed )
            # tell the OS to immediately abort the connection when calling socket.socket.close()
            client_exit_stack.callback(self.__set_socket_linger_if_not_closed, socket.socket())

            logger: logging.Logger = self.__logger
            backend = self.__backend
            producer = StreamDataProducer(self.__protocol)
            consumer = StreamDataConsumer(self.__protocol)
            client = _ConnectedClientAPI(backend, socket, producer, logger)
            request_receiver = _RequestReceiver(
                consumer,
                socket,
                self.__max_recv_size,
                client,
                logger,
            )

            client_exit_stack.callback(consumer.clear)
            client_exit_stack.callback(producer.clear)

            with _contextlib.suppress(OSError):
                set_tcp_nodelay(client.socket, True)
            with _contextlib.suppress(OSError):
                set_tcp_keepalive(client.socket, True)

            logger.log(self.__client_connection_log_level, "Accepted new connection (address = %s)", client.address)
            client_exit_stack.callback(self.__logger.log, self.__client_connection_log_level, "%s disconnected", client.address)
            client_exit_stack.push_async_callback(client._force_close)
            client_exit_stack.enter_context(self.__suppress_and_log_remaining_exception(client_address=client.address))

            request_handler_generator: AsyncGenerator[None, _RequestT] | None = None
            _on_connection_hook = self.__request_handler.on_connection(client)
            if inspect.isasyncgen(_on_connection_hook):
                try:
                    await _on_connection_hook.asend(None)
                except StopAsyncIteration:
                    pass
                else:
                    request_handler_generator = _on_connection_hook
            else:
                assert inspect.isawaitable(_on_connection_hook)  # nosec assert_used
                await _on_connection_hook
            del _on_connection_hook
            client_exit_stack.push_async_callback(self.__request_handler.on_disconnection, client)

            del client_exit_stack

            try:
                if client.is_closing():
                    return
                if request_handler_generator is None:
                    request_handler_generator = await self.__new_request_handler(client)
                    if request_handler_generator is None:
                        return
                async for action in request_receiver:
                    try:
                        await action.asend(request_handler_generator)
                    except StopAsyncIteration:
                        request_handler_generator = None
                    finally:
                        del action
                    await backend.cancel_shielded_coro_yield()
                    if client.is_closing():
                        break
                    if request_handler_generator is None:
                        request_handler_generator = await self.__new_request_handler(client)
                        if request_handler_generator is None:
                            break
            finally:
                if request_handler_generator is not None:
                    await request_handler_generator.aclose()

    async def __new_request_handler(self, client: _ConnectedClientAPI[_ResponseT]) -> AsyncGenerator[None, _RequestT] | None:
        request_handler_generator = self.__request_handler.handle(client)
        try:
            await anext(request_handler_generator)
        except StopAsyncIteration:
            return None
        return request_handler_generator

    async def __force_close_stream_socket(self, socket: AsyncStreamSocketAdapter) -> None:
        with _contextlib.suppress(OSError):
            async with self.__backend.move_on_after(0):
                await socket.aclose()

    @classmethod
    def __have_errno(cls, exc: OSError | BaseExceptionGroup[OSError], errnos: set[int]) -> bool:
        if isinstance(exc, BaseExceptionGroup):
            return any(cls.__have_errno(exc, errnos) for exc in exc.exceptions)
        return exc.errno in errnos

    @staticmethod
    def __set_socket_linger_if_not_closed(socket: ISocket) -> None:
        with _contextlib.suppress(OSError):
            if socket.fileno() > -1:
                enable_socket_linger(socket, timeout=0)

    @_contextlib.contextmanager
    def __suppress_and_log_remaining_exception(self, client_address: SocketAddress | None = None) -> Iterator[None]:
        try:
            if client_address is None:
                try:
                    yield
                except* OSError as excgrp:
                    if self.__have_errno(excgrp, {_errno.ENOTCONN, _errno.EINVAL}):
                        # The remote host closed the connection before starting the task.
                        # See this test for details:
                        # test____serve_forever____accept_client____client_sent_RST_packet_right_after_accept

                        self.__logger.warning("A client connection was interrupted just after listener.accept()")
                    else:
                        raise
            else:
                try:
                    yield
                except* ClientClosedError as excgrp:
                    _remove_traceback_frames_in_place(excgrp, 1)  # Removes the 'yield' frame just above
                    self.__logger.warning(
                        "There have been attempts to do operation on closed client %s",
                        client_address,
                        exc_info=True,
                    )
                except* ConnectionError:
                    # This exception come from the request handler ( most likely due to client.send_packet() )
                    # It is up to the user to log the ConnectionError stack trace
                    # There is already a "disconnected" info log
                    pass
        except Exception as exc:
            _remove_traceback_frames_in_place(exc, 1)  # Removes the 'yield' frame just above
            self.__logger.error("-" * 40)
            if client_address is None:
                self.__logger.exception("Error in client task")
            else:
                self.__logger.exception("Exception occurred during processing of request from %s", client_address)
            self.__logger.error("-" * 40)

    def get_addresses(self) -> Sequence[SocketAddress]:
        """
        Returns all interfaces to which the listeners are bound.

        Returns:
            A sequence of network socket address.
            If the server is not serving (:meth:`is_serving` returns :data:`False`), an empty sequence is returned.
        """
        if (listeners := self.__listeners) is None:
            return ()
        return tuple(
            new_socket_address(listener.socket().getsockname(), listener.socket().family)
            for listener in listeners
            if not listener.is_closing()
        )

    def get_backend(self) -> AsyncBackend:
        return self.__backend

    get_backend.__doc__ = AbstractAsyncNetworkServer.get_backend.__doc__

    @property
    def sockets(self) -> Sequence[SocketProxy]:
        """The listeners sockets. Read-only attribute."""
        if (listeners := self.__listeners) is None:
            return ()
        return tuple(SocketProxy(listener.socket()) for listener in listeners)

    @property
    def logger(self) -> logging.Logger:
        """The server's logger."""
        return self.__logger


class _RequestReceiver(Generic[_RequestT]):
    __slots__ = ("__consumer", "__socket", "__max_recv_size", "__api", "__logger")

    def __init__(
        self,
        consumer: StreamDataConsumer[_RequestT],
        socket: AsyncStreamSocketAdapter,
        max_recv_size: int,
        api: _ConnectedClientAPI[Any],
        logger: logging.Logger,
    ) -> None:
        assert max_recv_size > 0, f"{max_recv_size=}"  # nosec assert_used
        self.__consumer: StreamDataConsumer[_RequestT] = consumer
        self.__socket: AsyncStreamSocketAdapter = socket
        self.__max_recv_size: int = max_recv_size
        self.__api: _ConnectedClientAPI[Any] = api
        self.__logger: logging.Logger = logger

    def __aiter__(self) -> AsyncIterator[_RequestAction[_RequestT] | _ErrorAction]:
        return self

    async def __anext__(self) -> _RequestAction[_RequestT] | _ErrorAction:
        consumer: StreamDataConsumer[_RequestT] = self.__consumer
        socket: AsyncStreamSocketAdapter = self.__socket
        client: _ConnectedClientAPI[Any] = self.__api
        logger: logging.Logger = self.__logger
        bufsize: int = self.__max_recv_size
        try:
            while not socket.is_closing():
                try:
                    return _RequestAction(next(consumer))
                except StopIteration:
                    pass
                try:
                    data: bytes = await socket.recv(bufsize)
                except ConnectionError:
                    break
                try:
                    if not data:  # Closed connection (EOF)
                        break
                    logger.debug("Received %d bytes from %s", len(data), client.address)
                    consumer.feed(data)
                finally:
                    del data
        except BaseException as exc:
            return _ErrorAction(exc)
        raise StopAsyncIteration


@final
class _ConnectedClientAPI(AsyncStreamClient[_ResponseT]):
    __slots__ = (
        "__socket",
        "__closed",
        "__producer",
        "__send_lock",
        "__proxy",
        "__logger",
    )

    def __init__(
        self,
        backend: AsyncBackend,
        socket: AsyncStreamSocketAdapter,
        producer: StreamDataProducer[_ResponseT],
        logger: logging.Logger,
    ) -> None:
        super().__init__(new_socket_address(socket.socket().getpeername(), socket.socket().family))

        self.__socket: AsyncStreamSocketAdapter = socket
        self.__closed: bool = False
        self.__producer: StreamDataProducer[_ResponseT] = producer
        self.__send_lock = backend.create_lock()
        self.__proxy: SocketProxy = SocketProxy(socket.socket())
        self.__logger: logging.Logger = logger

    def is_closing(self) -> bool:
        return self.__closed or self.__socket.is_closing()

    async def _force_close(self) -> None:
        self.__closed = True
        async with self.__send_lock:  # If self.aclose() took the lock, wait for it to finish
            pass

    async def aclose(self) -> None:
        async with self.__send_lock:
            socket = self.__socket
            self.__closed = True
            with _contextlib.suppress(OSError):
                await socket.aclose()

    async def send_packet(self, packet: _ResponseT, /) -> None:
        self.__check_closed()
        self.__logger.debug("A response will be sent to %s", self.address)
        producer = self.__producer
        producer.queue(packet)
        del packet
        async with self.__send_lock:
            socket = self.__check_closed()
            if not producer.pending_packets():  # pragma: no cover
                # Someone else already flushed the producer queue while waiting for lock acquisition
                return
            await socket.sendall_fromiter(producer)
            _check_real_socket_state(self.socket)
            self.__logger.debug("Data sent to %s", self.address)

    def __check_closed(self) -> AsyncStreamSocketAdapter:
        socket = self.__socket
        if self.__closed:
            raise ClientClosedError("Closed client")
        return socket

    @property
    def socket(self) -> SocketProxy:
        return self.__proxy
