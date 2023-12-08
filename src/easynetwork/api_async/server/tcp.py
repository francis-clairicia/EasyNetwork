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

import contextlib
import inspect
import logging
import weakref
from collections import deque
from collections.abc import AsyncGenerator, Callable, Coroutine, Iterator, Mapping, Sequence
from typing import TYPE_CHECKING, Any, Generic, NoReturn, final

from ..._typevars import _RequestT, _ResponseT
from ...exceptions import ClientClosedError, ServerAlreadyRunning, ServerClosedError
from ...lowlevel import _asyncgen, _utils, constants
from ...lowlevel._final import runtime_final_class
from ...lowlevel.api_async.backend.factory import AsyncBackendFactory
from ...lowlevel.api_async.servers import stream as lowlevel_stream_server
from ...lowlevel.socket import (
    INETSocketAttribute,
    ISocket,
    SocketAddress,
    SocketProxy,
    enable_socket_linger,
    new_socket_address,
    set_tcp_keepalive,
    set_tcp_nodelay,
)
from ...protocol import StreamProtocol
from .abc import AbstractAsyncNetworkServer, SupportsEventSet
from .handler import AsyncStreamClient, AsyncStreamRequestHandler, INETClientAttribute

if TYPE_CHECKING:
    import ssl as _typing_ssl

    from ...lowlevel.api_async.backend.abc import AsyncBackend, CancelScope, IEvent, Task, TaskGroup
    from ...lowlevel.api_async.transports.abc import AsyncListener, AsyncStreamTransport


class AsyncTCPNetworkServer(AbstractAsyncNetworkServer, Generic[_RequestT, _ResponseT]):
    """
    An asynchronous network server for TCP connections.
    """

    __slots__ = (
        "__backend",
        "__servers",
        "__listeners_factory",
        "__listeners_factory_scope",
        "__protocol",
        "__request_handler",
        "__is_shutdown",
        "__shutdown_asked",
        "__max_recv_size",
        "__servers_tasks",
        "__mainloop_task",
        "__active_tasks",
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
        ssl: _typing_ssl.SSLContext | None = None,
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
            max_recv_size = constants.DEFAULT_STREAM_BUFSIZE
        if not isinstance(max_recv_size, int) or max_recv_size <= 0:
            raise ValueError("'max_recv_size' must be a strictly positive integer")

        if ssl_handshake_timeout is not None and not ssl:
            raise ValueError("ssl_handshake_timeout is only meaningful with ssl")

        if ssl_shutdown_timeout is not None and not ssl:
            raise ValueError("ssl_shutdown_timeout is only meaningful with ssl")

        def _value_or_default(value: float | None, default: float) -> float:
            return value if value is not None else default

        self.__listeners_factory: Callable[[], Coroutine[Any, Any, Sequence[AsyncListener[AsyncStreamTransport]]]] | None
        if ssl:
            self.__listeners_factory = _utils.make_callback(
                backend.create_ssl_over_tcp_listeners,
                host,
                port,
                backlog=backlog,
                ssl_context=ssl,
                ssl_handshake_timeout=_value_or_default(ssl_handshake_timeout, constants.SSL_HANDSHAKE_TIMEOUT),
                ssl_shutdown_timeout=_value_or_default(ssl_shutdown_timeout, constants.SSL_SHUTDOWN_TIMEOUT),
                reuse_port=reuse_port,
            )
        else:
            self.__listeners_factory = _utils.make_callback(
                backend.create_tcp_listeners,
                host,
                port,
                backlog=backlog,
                reuse_port=reuse_port,
            )
        self.__listeners_factory_scope: CancelScope | None = None

        self.__backend: AsyncBackend = backend
        self.__servers: tuple[lowlevel_stream_server.AsyncStreamServer[_RequestT, _ResponseT], ...] | None = None
        self.__protocol: StreamProtocol[_ResponseT, _RequestT] = protocol
        self.__request_handler: AsyncStreamRequestHandler[_RequestT, _ResponseT] = request_handler
        self.__is_shutdown: IEvent = self.__backend.create_event()
        self.__is_shutdown.set()
        self.__shutdown_asked: bool = False
        self.__max_recv_size: int = max_recv_size
        self.__servers_tasks: deque[Task[NoReturn]] = deque()
        self.__mainloop_task: Task[NoReturn] | None = None
        self.__logger: logging.Logger = logger or logging.getLogger(__name__)
        self.__client_connection_log_level: int
        if log_client_connection:
            self.__client_connection_log_level = logging.INFO
        else:
            self.__client_connection_log_level = logging.DEBUG
        self.__active_tasks: int = 0

    @_utils.inherit_doc(AbstractAsyncNetworkServer)
    def is_serving(self) -> bool:
        return self.__servers is not None and all(not server.is_closing() for server in self.__servers)

    def stop_listening(self) -> None:
        """
        Schedules the shutdown of all listener sockets.

        After that, all new connections will be refused, but the server will continue to run and handle
        previously accepted connections.

        Further calls to :meth:`is_serving` will return :data:`False`.
        """
        with contextlib.ExitStack() as exit_stack:
            for listener_task in self.__servers_tasks:
                exit_stack.callback(listener_task.cancel)
                del listener_task

    @_utils.inherit_doc(AbstractAsyncNetworkServer)
    async def server_close(self) -> None:
        if self.__listeners_factory_scope is not None:
            self.__listeners_factory_scope.cancel()
        self.__listeners_factory = None
        await self.__close_servers()

    async def __close_servers(self) -> None:
        async with contextlib.AsyncExitStack() as exit_stack:
            servers, self.__servers = self.__servers, None
            if servers is not None:
                for server in servers:
                    exit_stack.push_async_callback(server.aclose)
                    del server

            for server_task in self.__servers_tasks:
                server_task.cancel()
                exit_stack.push_async_callback(server_task.wait)
                del server_task

            await self.__backend.cancel_shielded_coro_yield()

    @_utils.inherit_doc(AbstractAsyncNetworkServer)
    async def shutdown(self) -> None:
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

    @_utils.inherit_doc(AbstractAsyncNetworkServer)
    async def serve_forever(self, *, is_up_event: SupportsEventSet | None = None) -> NoReturn:
        async with contextlib.AsyncExitStack() as server_exit_stack:
            # Wake up server
            if not self.__is_shutdown.is_set():
                raise ServerAlreadyRunning("Server is already running")
            self.__is_shutdown = is_shutdown = self.__backend.create_event()
            server_exit_stack.callback(is_shutdown.set)
            ################

            # Bind and activate
            assert self.__servers is None  # nosec assert_used
            assert self.__listeners_factory_scope is None  # nosec assert_used
            if self.__listeners_factory is None:
                raise ServerClosedError("Closed server")
            listeners: list[AsyncListener[AsyncStreamTransport]] = []
            try:
                with self.__backend.open_cancel_scope() as self.__listeners_factory_scope:
                    await self.__backend.coro_yield()
                    listeners.extend(await self.__listeners_factory())
                if self.__listeners_factory_scope.cancelled_caught():
                    raise ServerClosedError("Closed server")
            finally:
                self.__listeners_factory_scope = None
            if not listeners:
                raise OSError("empty listeners list")
            self.__servers = tuple(
                lowlevel_stream_server.AsyncStreamServer(
                    listener,
                    self.__protocol,
                    max_recv_size=self.__max_recv_size,
                    backend=self.__backend,
                )
                for listener in listeners
            )
            del listeners
            ###################

            # Final teardown
            server_exit_stack.callback(self.__logger.info, "Server stopped")
            server_exit_stack.push_async_callback(self.__close_servers)
            ################

            # Initialize request handler
            await self.__request_handler.service_init(
                await server_exit_stack.enter_async_context(contextlib.AsyncExitStack()),
                weakref.proxy(self),
            )
            ############################

            # Setup task group
            self.__active_tasks = 0
            server_exit_stack.callback(self.__servers_tasks.clear)
            task_group = await server_exit_stack.enter_async_context(self.__backend.create_task_group())
            server_exit_stack.callback(self.__logger.info, "Server loop break, waiting for remaining tasks...")
            ##################

            # Enable listener
            self.__servers_tasks.extend(task_group.start_soon(self.__serve, server, task_group) for server in self.__servers)
            self.__logger.info("Start serving at %s", ", ".join(map(str, self.get_addresses())))
            #################

            # Server is up
            if is_up_event is not None and not self.__shutdown_asked:
                is_up_event.set()
            ##############

            # Main loop
            self.__mainloop_task = task_group.start_soon(self.__backend.sleep_forever)
            if self.__shutdown_asked:
                self.__mainloop_task.cancel()
            try:
                await self.__mainloop_task.join()
            finally:
                self.__mainloop_task = None

        raise AssertionError("sleep_forever() does not return")

    async def __serve(
        self,
        server: lowlevel_stream_server.AsyncStreamServer[_RequestT, _ResponseT],
        task_group: TaskGroup,
    ) -> NoReturn:
        self.__attach_server()
        try:
            async with contextlib.aclosing(server):
                await server.serve(self.__client_coroutine, task_group)
        finally:
            self.__detach_server()

    async def __client_coroutine(
        self,
        lowlevel_client: lowlevel_stream_server.AsyncStreamClient[_ResponseT],
    ) -> AsyncGenerator[None, _RequestT]:
        async with contextlib.AsyncExitStack() as client_exit_stack:
            self.__attach_server()
            client_exit_stack.callback(self.__detach_server)

            client_address = lowlevel_client.extra(INETSocketAttribute.peername, None)
            if client_address is None:
                # The remote host closed the connection before starting the task.
                # See this test for details:
                # test____serve_forever____accept_client____client_sent_RST_packet_right_after_accept
                self.__logger.warning("A client connection was interrupted just after listener.accept()")
                return

            client_address = new_socket_address(client_address, lowlevel_client.extra(INETSocketAttribute.family))

            client_exit_stack.enter_context(self.__suppress_and_log_remaining_exception(client_address=client_address))
            # If the socket was not closed gracefully, (i.e. client.aclose() failed )
            # tell the OS to immediately abort the connection when calling socket.socket.close()
            client_exit_stack.callback(self.__set_socket_linger_if_not_closed, lowlevel_client.extra(INETSocketAttribute.socket))

            logger: logging.Logger = self.__logger
            backend: AsyncBackend = self.__backend
            client = _ConnectedClientAPI(client_address, backend, lowlevel_client, logger)

            del lowlevel_client

            logger.log(self.__client_connection_log_level, "Accepted new connection (address = %s)", client_address)
            client_exit_stack.callback(self.__logger.log, self.__client_connection_log_level, "%s disconnected", client_address)
            client_exit_stack.push_async_callback(client._force_close)

            request_handler_generator: AsyncGenerator[None, _RequestT] | None = None
            _on_connection_hook = self.__request_handler.on_connection(client)
            if isinstance(_on_connection_hook, AsyncGenerator):
                try:
                    await anext(_on_connection_hook)
                except StopAsyncIteration:
                    pass
                else:
                    request_handler_generator = _on_connection_hook
            else:
                assert inspect.isawaitable(_on_connection_hook)  # nosec assert_used
                await _on_connection_hook
            del _on_connection_hook

            async def disconnect_client() -> None:
                try:
                    await self.__request_handler.on_disconnection(client)
                except* ConnectionError:
                    self.__logger.warning("ConnectionError raised in request_handler.on_disconnection()")

            client_exit_stack.push_async_callback(disconnect_client)

            del client_exit_stack

            try:
                action: _asyncgen.AsyncGenAction[None, _RequestT]
                while not client.is_closing():
                    if request_handler_generator is None:
                        request_handler_generator = self.__request_handler.handle(client)
                        try:
                            await anext(request_handler_generator)
                        except StopAsyncIteration:
                            request_handler_generator = None
                            break
                    try:
                        action = _asyncgen.SendAction((yield))
                    except ConnectionError:
                        break
                    except BaseException as exc:
                        action = _asyncgen.ThrowAction(exc)
                    try:
                        await action.asend(request_handler_generator)
                    except StopAsyncIteration:
                        request_handler_generator = None
                    finally:
                        del action
                    await backend.cancel_shielded_coro_yield()
            finally:
                if request_handler_generator is not None:
                    await request_handler_generator.aclose()

    def __attach_server(self) -> None:
        self.__active_tasks += 1

    def __detach_server(self) -> None:
        self.__active_tasks -= 1
        if self.__active_tasks < 0:
            raise AssertionError("self.__active_tasks < 0")
        if not self.__active_tasks:
            if self.__mainloop_task is not None:
                self.__mainloop_task.cancel()

    @staticmethod
    def __set_socket_linger_if_not_closed(socket: ISocket) -> None:
        with contextlib.suppress(OSError):
            if socket.fileno() > -1:
                enable_socket_linger(socket, timeout=0)

    @contextlib.contextmanager
    def __suppress_and_log_remaining_exception(self, client_address: SocketAddress) -> Iterator[None]:
        try:
            try:
                yield
            except* ClientClosedError as excgrp:
                _utils.remove_traceback_frames_in_place(excgrp, 1)  # Removes the 'yield' frame just above
                self.__logger.warning(
                    "There have been attempts to do operation on closed client %s",
                    client_address,
                    exc_info=excgrp,
                )
            except* ConnectionError:
                # This exception come from the request handler ( most likely due to client.send_packet() )
                # It is up to the user to log the ConnectionError stack trace
                # There is already a "disconnected" info log
                pass
        except Exception as exc:
            _utils.remove_traceback_frames_in_place(exc, 1)  # Removes the 'yield' frame just above
            self.__logger.error("-" * 40)
            self.__logger.error("Exception occurred during processing of request from %s", client_address, exc_info=exc)
            self.__logger.error("-" * 40)

    @_utils.inherit_doc(AbstractAsyncNetworkServer)
    def get_addresses(self) -> Sequence[SocketAddress]:
        if (servers := self.__servers) is None:
            return ()
        return tuple(
            new_socket_address(server.extra(INETSocketAttribute.sockname), server.extra(INETSocketAttribute.family))
            for server in servers
            if not server.is_closing()
        )

    @_utils.inherit_doc(AbstractAsyncNetworkServer)
    def get_backend(self) -> AsyncBackend:
        return self.__backend

    @property
    def sockets(self) -> Sequence[SocketProxy]:
        """The listeners sockets. Read-only attribute."""
        if (servers := self.__servers) is None:
            return ()
        return tuple(SocketProxy(server.extra(INETSocketAttribute.socket)) for server in servers)

    @property
    def logger(self) -> logging.Logger:
        """The server's logger."""
        return self.__logger


@final
@runtime_final_class
class _ConnectedClientAPI(AsyncStreamClient[_ResponseT]):
    __slots__ = (
        "__client",
        "__closed",
        "__send_lock",
        "__address",
        "__proxy",
        "__logger",
    )

    def __init__(
        self,
        address: SocketAddress,
        backend: AsyncBackend,
        client: lowlevel_stream_server.AsyncStreamClient[_ResponseT],
        logger: logging.Logger,
    ) -> None:
        self.__client: lowlevel_stream_server.AsyncStreamClient[_ResponseT] = client
        self.__closed: bool = False
        self.__send_lock = backend.create_lock()
        self.__logger: logging.Logger = logger
        self.__proxy: SocketProxy = SocketProxy(client.extra(INETSocketAttribute.socket))
        self.__address: SocketAddress = address

        with contextlib.suppress(OSError):
            set_tcp_nodelay(self.__proxy, True)
        with contextlib.suppress(OSError):
            set_tcp_keepalive(self.__proxy, True)

    def __repr__(self) -> str:
        return f"<client with address {self.__address} at {id(self):#x}>"

    def is_closing(self) -> bool:
        return self.__closed or self.__client.is_closing()

    async def _force_close(self) -> None:
        self.__closed = True
        async with self.__send_lock:  # If self.aclose() took the lock, wait for it to finish
            pass

    async def aclose(self) -> None:
        async with self.__send_lock:
            self.__closed = True
            await self.__client.aclose()

    async def send_packet(self, packet: _ResponseT, /) -> None:
        self.__check_closed()
        self.__logger.debug("A response will be sent to %s", self.__address)
        async with self.__send_lock:
            self.__check_closed()
            await self.__client.send_packet(packet)
            _utils.check_real_socket_state(self.__proxy)
            self.__logger.debug("Data sent to %s", self.__address)

    def __check_closed(self) -> None:
        if self.__closed:
            raise ClientClosedError("Closed client")

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        client = self.__client
        return {
            **client.extra_attributes,
            INETClientAttribute.socket: lambda: self.__proxy,
            INETClientAttribute.local_address: lambda: new_socket_address(
                client.extra(INETSocketAttribute.sockname),
                client.extra(INETSocketAttribute.family),
            ),
            INETClientAttribute.remote_address: lambda: self.__address,
        }
