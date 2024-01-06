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

from ..._typevars import _T_Request, _T_Response
from ...exceptions import ClientClosedError, ServerAlreadyRunning, ServerClosedError
from ...lowlevel import _asyncgen, _utils, constants
from ...lowlevel._final import runtime_final_class
from ...lowlevel.api_async.backend.factory import current_async_backend
from ...lowlevel.api_async.servers import stream as _stream_server
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

    from ...lowlevel.api_async.backend.abc import CancelScope, IEvent, Task, TaskGroup
    from ...lowlevel.api_async.transports.abc import AsyncListener, AsyncStreamTransport


class AsyncTCPNetworkServer(AbstractAsyncNetworkServer, Generic[_T_Request, _T_Response]):
    """
    An asynchronous network server for TCP connections.
    """

    __slots__ = (
        "__servers",
        "__listeners_factory",
        "__listeners_factory_scope",
        "__protocol",
        "__request_handler",
        "__is_shutdown",
        "__max_recv_size",
        "__servers_tasks",
        "__server_run_scope",
        "__active_tasks",
        "__client_connection_log_level",
        "__logger",
    )

    def __init__(
        self,
        host: str | None | Sequence[str],
        port: int,
        protocol: StreamProtocol[_T_Response, _T_Request],
        request_handler: AsyncStreamRequestHandler[_T_Request, _T_Response],
        *,
        ssl: _typing_ssl.SSLContext | None = None,
        ssl_handshake_timeout: float | None = None,
        ssl_shutdown_timeout: float | None = None,
        backlog: int | None = None,
        reuse_port: bool = False,
        max_recv_size: int | None = None,
        log_client_connection: bool | None = None,
        logger: logging.Logger | None = None,
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

        See Also:
            :ref:`SSL/TLS security considerations <ssl-security>`
        """
        super().__init__()

        if not isinstance(protocol, StreamProtocol):
            raise TypeError(f"Expected a StreamProtocol object, got {protocol!r}")
        if not isinstance(request_handler, AsyncStreamRequestHandler):
            raise TypeError(f"Expected an AsyncStreamRequestHandler object, got {request_handler!r}")

        backend = current_async_backend()

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
        self.__server_run_scope: CancelScope | None = None

        self.__servers: tuple[_stream_server.AsyncStreamServer[_T_Request, _T_Response], ...] | None = None
        self.__protocol: StreamProtocol[_T_Response, _T_Request] = protocol
        self.__request_handler: AsyncStreamRequestHandler[_T_Request, _T_Response] = request_handler
        self.__is_shutdown: IEvent = backend.create_event()
        self.__is_shutdown.set()
        self.__max_recv_size: int = max_recv_size
        self.__servers_tasks: deque[Task[NoReturn]] = deque()
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
            server_close_group = await exit_stack.enter_async_context(current_async_backend().create_task_group())

            servers, self.__servers = self.__servers, None
            if servers is not None:
                exit_stack.push_async_callback(current_async_backend().cancel_shielded_coro_yield)
                for server in servers:
                    exit_stack.callback(server_close_group.start_soon, server.aclose)
                    del server

            for server_task in self.__servers_tasks:
                server_task.cancel()
                exit_stack.push_async_callback(server_task.wait)
                del server_task

            if self.__server_run_scope is not None:
                self.__server_run_scope.cancel()

            await current_async_backend().cancel_shielded_coro_yield()

    @_utils.inherit_doc(AbstractAsyncNetworkServer)
    async def shutdown(self) -> None:
        if self.__server_run_scope is not None:
            self.__server_run_scope.cancel()
        await self.__is_shutdown.wait()

    @_utils.inherit_doc(AbstractAsyncNetworkServer)
    async def serve_forever(self, *, is_up_event: SupportsEventSet | None = None) -> None:
        async with contextlib.AsyncExitStack() as server_exit_stack:
            # Wake up server
            if not self.__is_shutdown.is_set():
                raise ServerAlreadyRunning("Server is already running")
            self.__is_shutdown = is_shutdown = current_async_backend().create_event()
            server_exit_stack.callback(is_shutdown.set)
            self.__server_run_scope = server_exit_stack.enter_context(current_async_backend().open_cancel_scope())

            def reset_scope() -> None:
                self.__server_run_scope = None

            server_exit_stack.callback(reset_scope)
            ################

            # Bind and activate
            assert self.__servers is None  # nosec assert_used
            assert self.__listeners_factory_scope is None  # nosec assert_used
            if self.__listeners_factory is None:
                raise ServerClosedError("Closed server")
            listeners: list[AsyncListener[AsyncStreamTransport]] = []
            try:
                with current_async_backend().open_cancel_scope() as self.__listeners_factory_scope:
                    await current_async_backend().coro_yield()
                    listeners.extend(await self.__listeners_factory())
                if self.__listeners_factory_scope.cancelled_caught():
                    raise ServerClosedError("Server has been closed during task setup")
            finally:
                self.__listeners_factory_scope = None
            if not listeners:
                raise OSError("empty listeners list")
            self.__servers = tuple(
                _stream_server.AsyncStreamServer(listener, self.__protocol, max_recv_size=self.__max_recv_size)
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
            task_group = await server_exit_stack.enter_async_context(current_async_backend().create_task_group())
            server_exit_stack.callback(self.__logger.info, "Server loop break, waiting for remaining tasks...")
            ##################

            # Enable listener
            self.__servers_tasks.extend([await task_group.start(self.__serve, server, task_group) for server in self.__servers])
            self.__logger.info("Start serving at %s", ", ".join(map(str, self.get_addresses())))
            #################

            # Server is up
            if is_up_event is not None:
                is_up_event.set()
            ##############

            # Main loop
            try:
                await current_async_backend().sleep_forever()
            finally:
                reset_scope()

    async def __serve(
        self,
        server: _stream_server.AsyncStreamServer[_T_Request, _T_Response],
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
        lowlevel_client: _stream_server.AsyncStreamClient[_T_Response],
    ) -> AsyncGenerator[None, _T_Request]:
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
            client = _ConnectedClientAPI(client_address, lowlevel_client)

            del lowlevel_client

            logger.log(self.__client_connection_log_level, "Accepted new connection (address = %s)", client_address)
            client_exit_stack.callback(logger.log, self.__client_connection_log_level, "%s disconnected", client_address)
            client_exit_stack.push_async_callback(client._force_close)

            request_handler_generator: AsyncGenerator[None, _T_Request]
            action: _asyncgen.AsyncGenAction[None, _T_Request]

            SendAction = _asyncgen.SendAction
            ThrowAction = _asyncgen.ThrowAction

            _on_connection_hook = self.__request_handler.on_connection(client)
            if isinstance(_on_connection_hook, AsyncGenerator):
                try:
                    await anext(_on_connection_hook)
                except StopAsyncIteration:
                    pass
                else:
                    while True:
                        try:
                            action = SendAction((yield))
                        except ConnectionError:
                            await _on_connection_hook.aclose()
                            return
                        except BaseException as exc:
                            action = ThrowAction(_utils.remove_traceback_frames_in_place(exc, 1))
                        try:
                            await action.asend(_on_connection_hook)
                        except StopAsyncIteration:
                            break
                        except BaseException as exc:
                            # Remove action.asend() frames
                            _utils.remove_traceback_frames_in_place(exc, 2)
                            raise
                        finally:
                            del action
            else:
                assert inspect.isawaitable(_on_connection_hook)  # nosec assert_used
                await _on_connection_hook
            del _on_connection_hook

            async def disconnect_client() -> None:
                try:
                    await self.__request_handler.on_disconnection(client)
                except* ConnectionError:
                    logger.warning("ConnectionError raised in request_handler.on_disconnection()")

            client_exit_stack.push_async_callback(disconnect_client)

            del client_exit_stack

            new_request_handler = self.__request_handler.handle
            client_is_closing = client.is_closing

            while not client_is_closing():
                request_handler_generator = new_request_handler(client)
                try:
                    await anext(request_handler_generator)
                except StopAsyncIteration:
                    return
                while True:
                    try:
                        action = SendAction((yield))
                    except ConnectionError:
                        await request_handler_generator.aclose()
                        return
                    except BaseException as exc:
                        action = ThrowAction(_utils.remove_traceback_frames_in_place(exc, 1))
                    try:
                        await action.asend(request_handler_generator)
                    except StopAsyncIteration:
                        break
                    except BaseException as exc:
                        # Remove action.asend() frames
                        _utils.remove_traceback_frames_in_place(exc, 2)
                        raise
                    finally:
                        del action

    def __attach_server(self) -> None:
        self.__active_tasks += 1

    def __detach_server(self) -> None:
        self.__active_tasks -= 1
        if self.__active_tasks < 0:
            raise AssertionError("self.__active_tasks < 0")
        if not self.__active_tasks and self.__server_run_scope is not None:
            self.__server_run_scope.cancel()

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

    def get_sockets(self) -> Sequence[SocketProxy]:
        """Gets the listeners sockets.

        Returns:
            a read-only sequence of :class:`.SocketProxy` objects.

            If the server is not running, an empty sequence is returned.
        """
        if (servers := self.__servers) is None:
            return ()
        return tuple(SocketProxy(server.extra(INETSocketAttribute.socket)) for server in servers)


@final
@runtime_final_class
class _ConnectedClientAPI(AsyncStreamClient[_T_Response]):
    __slots__ = (
        "__client",
        "__closed",
        "__send_lock",
        "__address",
        "__proxy",
        "__extra_attributes_cache",
    )

    def __init__(
        self,
        address: SocketAddress,
        client: _stream_server.AsyncStreamClient[_T_Response],
    ) -> None:
        self.__client: _stream_server.AsyncStreamClient[_T_Response] = client
        self.__closed: bool = False
        self.__send_lock = current_async_backend().create_lock()
        self.__proxy: SocketProxy = SocketProxy(client.extra(INETSocketAttribute.socket))
        self.__address: SocketAddress = address
        self.__extra_attributes_cache: Mapping[Any, Callable[[], Any]] | None = None

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

    async def send_packet(self, packet: _T_Response, /) -> None:
        async with self.__send_lock:
            if self.__closed:
                raise ClientClosedError("Closed client")
            await self.__client.send_packet(packet)

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        if (extra_attributes_cache := self.__extra_attributes_cache) is not None:
            return extra_attributes_cache
        client = self.__client
        self.__extra_attributes_cache = extra_attributes_cache = {
            **client.extra_attributes,
            INETClientAttribute.socket: lambda: self.__proxy,
            INETClientAttribute.local_address: lambda: new_socket_address(
                client.extra(INETSocketAttribute.sockname),
                client.extra(INETSocketAttribute.family),
            ),
            INETClientAttribute.remote_address: lambda: self.__address,
        }
        return extra_attributes_cache
