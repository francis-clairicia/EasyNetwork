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
"""Asynchronous TCP Network server implementation module."""

from __future__ import annotations

__all__ = ["AsyncTCPNetworkServer"]

import contextlib
import logging
import weakref
from collections.abc import AsyncIterator, Callable, Coroutine, Iterator, Mapping, Sequence
from typing import TYPE_CHECKING, Any, Generic, NoReturn, final

from .._typevars import _T_Request, _T_Response
from ..exceptions import ClientClosedError
from ..lowlevel import _utils, constants
from ..lowlevel._final import runtime_final_class
from ..lowlevel.api_async.backend.abc import AsyncBackend, TaskGroup
from ..lowlevel.api_async.backend.utils import BuiltinAsyncBackendLiteral
from ..lowlevel.api_async.servers import stream as _stream_server
from ..lowlevel.api_async.transports.abc import AsyncListener, AsyncStreamTransport
from ..lowlevel.socket import (
    INETSocketAttribute,
    ISocket,
    SocketAddress,
    SocketProxy,
    TLSAttribute,
    enable_socket_linger,
    new_socket_address,
    set_tcp_keepalive,
    set_tcp_nodelay,
)
from ..protocol import AnyStreamProtocolType
from . import _base
from .handlers import AsyncStreamClient, AsyncStreamRequestHandler, INETClientAttribute
from .misc import build_lowlevel_stream_server_handler

if TYPE_CHECKING:
    from ssl import SSLContext


class AsyncTCPNetworkServer(
    _base.BaseAsyncNetworkServerImpl[_stream_server.AsyncStreamServer[_T_Request, _T_Response], SocketAddress],
    Generic[_T_Request, _T_Response],
):
    """
    An asynchronous network server for TCP connections.
    """

    __slots__ = (
        "__listeners_factory",
        "__protocol",
        "__request_handler",
        "__max_recv_size",
        "__client_connection_log_level",
    )

    def __init__(
        self,
        host: str | None | Sequence[str],
        port: int,
        protocol: AnyStreamProtocolType[_T_Response, _T_Request],
        request_handler: AsyncStreamRequestHandler[_T_Request, _T_Response],
        backend: AsyncBackend | BuiltinAsyncBackendLiteral | None = None,
        *,
        ssl: SSLContext | None = None,
        ssl_handshake_timeout: float | None = None,
        ssl_shutdown_timeout: float | None = None,
        ssl_standard_compatible: bool | None = None,
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
            backend: The :term:`asynchronous backend interface` to use.

        Keyword Arguments:
            ssl: can be set to an :class:`ssl.SSLContext` instance to enable TLS over the accepted connections.
            ssl_handshake_timeout: (for a TLS connection) the time in seconds to wait for the TLS handshake to complete
                                   before aborting the connection. ``60.0`` seconds if :data:`None` (default).
            ssl_shutdown_timeout: the time in seconds to wait for the SSL shutdown to complete before aborting the connection.
                                  ``30.0`` seconds if :data:`None` (default).
            ssl_standard_compatible: if :data:`False`, skip the closing handshake when closing the connection,
                                     and don't raise an exception if the peer does the same.
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
        super().__init__(
            backend=backend,
            servers_factory=type(self).__activate_listeners,
            initialize_service=type(self).__initialize_service,
            lowlevel_serve=type(self).__lowlevel_serve,
            logger=logger or logging.getLogger(__name__),
        )

        from ..lowlevel._stream import _check_any_protocol

        _check_any_protocol(protocol)

        if not isinstance(request_handler, AsyncStreamRequestHandler):
            raise TypeError(f"Expected an AsyncStreamRequestHandler object, got {request_handler!r}")

        backend = self.backend()

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

        if ssl_standard_compatible is not None and not ssl:
            raise ValueError("ssl_standard_compatible is only meaningful with ssl")

        if ssl_standard_compatible is None:
            ssl_standard_compatible = True

        self.__listeners_factory: Callable[[], Coroutine[Any, Any, Sequence[AsyncListener[AsyncStreamTransport]]]]
        if ssl:
            self.__listeners_factory = _utils.make_callback(
                self.__create_ssl_over_tcp_listeners,
                backend,
                host,
                port,
                backlog=backlog,
                ssl_context=ssl,
                ssl_handshake_timeout=ssl_handshake_timeout,
                ssl_shutdown_timeout=ssl_shutdown_timeout,
                ssl_standard_compatible=ssl_standard_compatible,
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

        self.__protocol: AnyStreamProtocolType[_T_Response, _T_Request] = protocol
        self.__request_handler: AsyncStreamRequestHandler[_T_Request, _T_Response] = request_handler
        self.__max_recv_size: int = max_recv_size
        self.__client_connection_log_level: int
        if log_client_connection:
            self.__client_connection_log_level = logging.INFO
        else:
            self.__client_connection_log_level = logging.DEBUG

    @staticmethod
    async def __create_ssl_over_tcp_listeners(
        backend: AsyncBackend,
        host: str | Sequence[str] | None,
        port: int,
        backlog: int,
        ssl_context: SSLContext,
        *,
        ssl_handshake_timeout: float | None,
        ssl_shutdown_timeout: float | None,
        ssl_standard_compatible: bool,
        reuse_port: bool,
    ) -> Sequence[AsyncListener[AsyncStreamTransport]]:
        from ..lowlevel.api_async.transports.tls import AsyncTLSListener

        listeners = await backend.create_tcp_listeners(
            host=host,
            port=port,
            backlog=backlog,
            reuse_port=reuse_port,
        )
        return [
            AsyncTLSListener(
                listener,
                ssl_context,
                handshake_timeout=ssl_handshake_timeout,
                shutdown_timeout=ssl_shutdown_timeout,
                standard_compatible=ssl_standard_compatible,
            )
            for listener in listeners
        ]

    async def __activate_listeners(self) -> list[_stream_server.AsyncStreamServer[_T_Request, _T_Response]]:
        return [
            _stream_server.AsyncStreamServer(
                listener,
                self.__protocol,
                max_recv_size=self.__max_recv_size,
            )
            for listener in await self.__listeners_factory()
        ]

    async def __initialize_service(self, server_exit_stack: contextlib.AsyncExitStack) -> None:
        await self.__request_handler.service_init(
            await server_exit_stack.enter_async_context(contextlib.AsyncExitStack()),
            weakref.proxy(self),
        )

    async def __lowlevel_serve(
        self,
        server: _stream_server.AsyncStreamServer[_T_Request, _T_Response],
        task_group: TaskGroup,
    ) -> NoReturn:
        def disconnect_error_filter(exc: Exception) -> bool:
            match exc:
                case ConnectionError():
                    return True
                case _:
                    return _utils.is_ssl_eof_error(exc)

        handler = build_lowlevel_stream_server_handler(
            self.__client_initializer,
            self.__request_handler,
            logger=self.logger,
        )
        await server.serve(
            handler,
            task_group,
            disconnect_error_filter=disconnect_error_filter,
        )

    @contextlib.asynccontextmanager
    async def __client_initializer(
        self,
        lowlevel_client: _stream_server.ConnectedStreamClient[_T_Response],
    ) -> AsyncIterator[AsyncStreamClient[_T_Response] | None]:
        async with contextlib.AsyncExitStack() as client_exit_stack:
            client_exit_stack.enter_context(self._bind_server())

            client_address = lowlevel_client.extra(INETSocketAttribute.peername, None)
            if client_address is None:
                # The remote host closed the connection before starting the task.
                # See this test for details:
                # test____serve_forever____accept_client____client_sent_RST_packet_right_after_accept
                self.logger.warning("A client connection was interrupted just after listener.accept()")
                yield None
                return

            client_address = new_socket_address(client_address, lowlevel_client.extra(INETSocketAttribute.family))

            client_exit_stack.enter_context(self.__suppress_and_log_remaining_exception(client_address=client_address))
            # If the socket was not closed gracefully, (i.e. client.aclose() failed )
            # tell the OS to immediately abort the connection when calling socket.socket.close()
            # NOTE: Do not set this option if SSL/TLS is enabled
            if lowlevel_client.extra(TLSAttribute.sslcontext, None) is None:
                client_exit_stack.callback(
                    self.__set_socket_linger_if_not_closed,
                    lowlevel_client.extra(INETSocketAttribute.socket),
                )
            elif lowlevel_client.extra(TLSAttribute.standard_compatible, False):
                # We expect a TLS close handshake, so we must (try to) properly close the transport before
                await client_exit_stack.enter_async_context(contextlib.aclosing(lowlevel_client))

            logger: logging.Logger = self.logger
            client = _ConnectedClientAPI(client_address, lowlevel_client)

            del lowlevel_client

            logger.log(self.__client_connection_log_level, "Accepted new connection (address = %s)", client_address)
            client_exit_stack.callback(logger.log, self.__client_connection_log_level, "%s disconnected", client_address)
            client_exit_stack.push_async_callback(client._force_close)

            try:
                yield client
            except BaseException as exc:
                _utils.remove_traceback_frames_in_place(exc, 1)
                raise

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
                self.logger.warning(
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
            self.logger.error("-" * 40)
            self.logger.error("Exception occurred during processing of request from %s", client_address, exc_info=exc)
            self.logger.error("-" * 40)

    @_utils.inherit_doc(_base.BaseAsyncNetworkServerImpl)
    def get_addresses(self) -> Sequence[SocketAddress]:
        return self._with_lowlevel_servers(
            lambda servers: tuple(
                new_socket_address(server.extra(INETSocketAttribute.sockname), server.extra(INETSocketAttribute.family))
                for server in servers
                if not server.is_closing()
            )
        )

    def get_sockets(self) -> Sequence[SocketProxy]:
        """Gets the listeners sockets.

        Returns:
            a read-only sequence of :class:`.SocketProxy` objects.

            If the server is not running, an empty sequence is returned.
        """
        return self._with_lowlevel_servers(
            lambda servers: tuple(SocketProxy(server.extra(INETSocketAttribute.socket)) for server in servers)
        )


@final
@runtime_final_class
class _ConnectedClientAPI(AsyncStreamClient[_T_Response]):
    __slots__ = (
        "__client",
        "__closing",
        "__send_lock",
        "__address",
        "__proxy",
        "__extra_attributes_cache",
    )

    def __init__(
        self,
        address: SocketAddress,
        client: _stream_server.ConnectedStreamClient[_T_Response],
    ) -> None:
        self.__client: _stream_server.ConnectedStreamClient[_T_Response] = client
        self.__closing: bool = False
        self.__send_lock = client.backend().create_fair_lock()
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
        return self.__closing

    async def _force_close(self) -> None:
        self.__closing = True
        async with self.__send_lock:  # If self.aclose() took the lock, wait for it to finish
            pass

    async def aclose(self) -> None:
        async with self.__send_lock:
            self.__closing = True
            await self.__client.aclose()

    async def send_packet(self, packet: _T_Response, /) -> None:
        async with self.__send_lock:
            if self.__closing:
                raise ClientClosedError("Closed client")
            await self.__client.send_packet(packet)

    def backend(self) -> AsyncBackend:
        return self.__client.backend()

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
