# Copyright 2021-2026, Francis Clairicia-Rose-Claire-Josephine
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
"""Multi-threaded TCP Network server implementation module.

.. versionadded:: NEXT_VERSION
"""

from __future__ import annotations

__all__ = ["ThreadedTCPNetworkServer"]

import concurrent.futures
import contextlib
import logging
import socket as _socket
import threading
import weakref
from collections.abc import Callable, Generator, Mapping, Sequence
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal, final, override

from ..exceptions import ClientClosedError
from ..lowlevel import _utils
from ..lowlevel._final import runtime_final_class
from ..lowlevel.api_sync.servers import selector_stream as _stream_server
from ..lowlevel.api_sync.transports.socket import SocketStreamListener, SSLStreamListener
from ..lowlevel.socket import (
    INETSocketAttribute,
    SocketAddress,
    SocketProxy,
    TLSAttribute,
    new_socket_address,
    set_tcp_keepalive,
    set_tcp_nodelay,
)
from ..protocol import AnyStreamProtocolType
from . import _base
from .handlers import BlockingStreamClient, BlockingStreamRequestHandler, INETClientAttribute
from .misc import build_lowlevel_blocking_stream_server_handler

if TYPE_CHECKING:
    from ssl import SSLContext


class ThreadedTCPNetworkServer[Request, Response](
    _base.BaseThreadedNetworkServerImpl[_stream_server.SelectorStreamServer[Request, Response], SocketAddress],
):
    """
    A multi-threaded network server for TCP connections.

    .. versionadded:: NEXT_VERSION
    """

    __slots__ = (
        "__listeners_factory",
        "__protocol",
        "__request_handler",
        "__max_recv_size",
        "__worker_strategy",
        "__client_connection_log_level",
    )

    def __init__(
        self,
        host: str | None | Sequence[str],
        port: int,
        protocol: AnyStreamProtocolType[Response, Request],
        request_handler: BlockingStreamRequestHandler[Request, Response],
        *,
        ssl: SSLContext | None = None,
        ssl_handshake_timeout: float | None = None,
        ssl_shutdown_timeout: float | None = None,
        ssl_standard_compatible: bool | None = None,
        backlog: int | None = None,
        reuse_port: bool = False,
        max_recv_size: int | None = None,
        max_nb_workers: int | None = None,
        worker_strategy: Literal["clients", "requests"] = "requests",
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
            ssl_standard_compatible: if :data:`False`, skip the closing handshake when closing the connection,
                                     and don't raise an exception if the peer does the same.
            backlog: is the maximum number of queued connections passed to :class:`~socket.socket.listen` (defaults to ``100``).
            reuse_port: Tells the kernel to allow this endpoint to be bound to the same port as other existing
                        endpoints are bound to, so long as they all set this flag when being created.
                        This option is not supported on Windows and some Unixes.
                        If the SO_REUSEPORT constant is not defined then this capability is unsupported.
            max_nb_workers: Use a pool of at most the given value.
            max_recv_size: Read buffer size. If not given, a default reasonable value is used.
            worker_strategy: Decides how to manage the executor.
            log_client_connection: If :data:`True` (default), log clients connection/disconnection in :data:`~logging.INFO` level.
                                   (This log will always be available in :data:`~logging.DEBUG` level.)
            logger: If given, the logger instance to use.

        See Also:
            :ref:`SSL/TLS security considerations <ssl-security>`
        """
        super().__init__(
            servers_factory=_utils.weak_method_proxy(self.__activate_listeners),
            initialize_service=_utils.weak_method_proxy(self.__initialize_service),
            lowlevel_serve=_utils.weak_method_proxy(self.__lowlevel_serve),
            logger=logger or logging.getLogger(__name__),
            max_nb_workers=max_nb_workers,
        )

        from ..lowlevel._stream import _check_any_protocol

        _check_any_protocol(protocol)

        if not isinstance(request_handler, BlockingStreamRequestHandler):
            raise TypeError(f"Expected an BlockingStreamRequestHandler object, got {request_handler!r}")

        if backlog is None:
            backlog = 100

        if log_client_connection is None:
            log_client_connection = True

        max_recv_size = _base.validate_max_recv_size(max_recv_size)

        _base.validate_ssl_arguments(
            ssl=ssl,
            ssl_handshake_timeout=ssl_handshake_timeout,
            ssl_shutdown_timeout=ssl_shutdown_timeout,
            ssl_standard_compatible=ssl_standard_compatible,
        )

        if ssl_standard_compatible is None:
            ssl_standard_compatible = True

        self.__listeners_factory: Callable[[], Sequence[SocketStreamListener | SSLStreamListener]]
        if ssl:
            self.__listeners_factory = _utils.make_callback(
                self.__create_ssl_over_tcp_listeners,
                host,
                port,
                backlog=backlog,
                ssl_context=ssl,
                ssl_handshake_timeout=ssl_handshake_timeout,
                ssl_shutdown_timeout=ssl_shutdown_timeout,
                ssl_standard_compatible=ssl_standard_compatible,
                reuse_port=reuse_port,
                logger=self.logger,
            )
        else:
            self.__listeners_factory = _utils.make_callback(
                self.__create_tcp_listeners,
                host,
                port,
                backlog=backlog,
                reuse_port=reuse_port,
            )

        self.__protocol: AnyStreamProtocolType[Response, Request] = protocol
        self.__request_handler: BlockingStreamRequestHandler[Request, Response] = request_handler
        self.__max_recv_size: int = max_recv_size
        self.__worker_strategy: Literal["clients", "requests"] = worker_strategy
        self.__client_connection_log_level: int = logging.INFO if log_client_connection else logging.DEBUG

    @classmethod
    def __create_tcp_listeners(
        cls,
        host: str | Sequence[str] | None,
        port: int,
        *,
        backlog: int,
        reuse_port: bool,
    ) -> Sequence[SocketStreamListener]:
        sockets = cls.__create_listener_sockets(host, port, backlog=backlog, reuse_port=reuse_port)
        return [SocketStreamListener(sock) for sock in sockets]

    @classmethod
    def __create_ssl_over_tcp_listeners(
        cls,
        host: str | Sequence[str] | None,
        port: int,
        *,
        backlog: int,
        ssl_context: SSLContext,
        ssl_handshake_timeout: float | None,
        ssl_shutdown_timeout: float | None,
        ssl_standard_compatible: bool,
        reuse_port: bool,
        logger: logging.Logger,
    ) -> Sequence[SSLStreamListener]:
        from functools import partial

        sockets = cls.__create_listener_sockets(host, port, backlog=backlog, reuse_port=reuse_port)
        return [
            SSLStreamListener(
                sock,
                ssl_context,
                handshake_timeout=ssl_handshake_timeout,
                shutdown_timeout=ssl_shutdown_timeout,
                standard_compatible=ssl_standard_compatible,
                handshake_error_handler=partial(_base.ClientErrorHandler.client_tls_handshake_error_handler, logger),
            )
            for sock in sockets
        ]

    @classmethod
    def __create_listener_sockets(
        cls,
        host: str | Sequence[str] | None,
        port: int,
        *,
        backlog: int,
        reuse_port: bool,
    ) -> list[_socket.socket]:
        reuse_address = _utils.should_listener_reuse_address_on_current_platform()
        hosts = _utils.validate_listener_hosts(host)
        del host

        infos: Sequence[tuple[int, int, int, str, tuple[Any, ...]]] = _base.resolve_listener_addresses(
            hosts,
            port,
            _socket.SOCK_STREAM,
        )

        sockets: list[_socket.socket] = _utils.open_listener_sockets_from_getaddrinfo_result(
            infos,
            reuse_address=reuse_address,
            reuse_port=reuse_port,
            on_bind_success=lambda sock: sock.listen(backlog),
        )
        return sockets

    def __activate_listeners(self) -> list[_stream_server.SelectorStreamServer[Request, Response]]:
        return [
            _stream_server.SelectorStreamServer(
                listener,
                self.__protocol,
                max_recv_size=self.__max_recv_size,
            )
            for listener in self.__listeners_factory()
        ]

    def __initialize_service(self, server_exit_stack: contextlib.ExitStack) -> None:
        self.__request_handler.service_init(
            server_exit_stack.enter_context(contextlib.ExitStack()),
            weakref.proxy(self),
        )

    def __lowlevel_serve(
        self,
        server: _stream_server.SelectorStreamServer[Request, Response],
        executor: concurrent.futures.ThreadPoolExecutor,
    ) -> None:
        def disconnect_error_filter(exc: Exception) -> bool:
            match exc:
                case ConnectionError():
                    return True
                case _:
                    return _utils.is_ssl_eof_error(exc)

        handler = build_lowlevel_blocking_stream_server_handler(
            self.__client_initializer,
            self.__request_handler,
            logger=self.logger,
        )
        server.serve(
            handler,
            executor,
            worker_strategy=self.__worker_strategy,
            disconnect_error_filter=disconnect_error_filter,
        )

    @contextlib.contextmanager
    def __client_initializer(
        self,
        lowlevel_client: _stream_server.ConnectedStreamClient[Response],
    ) -> Generator[BlockingStreamClient[Response] | None]:
        with contextlib.ExitStack() as client_exit_stack:
            client_exit_stack.enter_context(self._bind_server())

            client_address = lowlevel_client.extra(INETSocketAttribute.peername, None)
            if client_address is None:
                yield None
                return

            client_address = new_socket_address(client_address, lowlevel_client.extra(INETSocketAttribute.family))
            client = _ConnectedClientAPI(client_address, lowlevel_client)

            client_exit_stack.enter_context(
                _base.ClientErrorHandler(
                    logger=self.logger,
                    client_address_cb=client.extra_attributes[INETClientAttribute.remote_address],
                    suppress_errors=ConnectionError,
                )
            )
            # If the socket was not closed gracefully, (i.e. client.aclose() failed )
            # tell the OS to immediately abort the connection when calling socket.socket.close()
            # NOTE: Do not set this option if SSL/TLS is enabled
            if lowlevel_client.extra(TLSAttribute.sslcontext, None) is None:
                client_exit_stack.callback(
                    _base.ClientErrorHandler.set_socket_linger_if_not_closed,
                    lowlevel_client.extra(INETSocketAttribute.socket),
                )

            del lowlevel_client

            self.logger.log(self.__client_connection_log_level, "Accepted new connection (address = %s)", client_address)
            client_exit_stack.callback(self.logger.log, self.__client_connection_log_level, "%s disconnected", client_address)
            client_exit_stack.callback(client._on_disconnect)

            try:
                yield client
            except BaseException as exc:
                _utils.remove_traceback_frames_in_place(exc, 1)
                raise

    @override
    @_utils.inherit_doc(_base.BaseThreadedNetworkServerImpl)
    def get_addresses(self) -> Sequence[SocketAddress]:
        return self._with_lowlevel_servers(
            lambda servers: tuple(
                new_socket_address(server.extra(INETSocketAttribute.sockname), server.extra(INETSocketAttribute.family))
                for server in servers
                if not server.is_closed()
            )
        )

    def get_sockets(self) -> Sequence[SocketProxy]:
        """Gets the listeners sockets.

        Returns:
            a read-only sequence of :class:`.SocketProxy` objects.

            If the server is not running, an empty sequence is returned.
        """
        return self._with_lowlevel_servers(
            lambda servers: tuple(
                SocketProxy(server.extra(INETSocketAttribute.socket)) for server in servers if not server.is_closed()
            )
        )


@final
@runtime_final_class
class _ConnectedClientAPI[Response](BlockingStreamClient[Response]):
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
        client: _stream_server.ConnectedStreamClient[Response],
    ) -> None:
        self.__client: _stream_server.ConnectedStreamClient[Response] = client
        self.__closing = threading.Event()
        self.__send_lock = threading.Lock()
        self.__proxy: SocketProxy = SocketProxy(client.extra(INETSocketAttribute.socket))
        self.__address: SocketAddress = address

        local_address = new_socket_address(client.extra(INETSocketAttribute.sockname), client.extra(INETSocketAttribute.family))

        self.__extra_attributes_cache: Mapping[Any, Callable[[], Any]] = MappingProxyType(
            {
                **client.extra_attributes,
                INETClientAttribute.socket: _utils.make_callback(self.__simple_attribute_return, self.__proxy),
                INETClientAttribute.local_address: _utils.make_callback(self.__simple_attribute_return, local_address),
                INETClientAttribute.remote_address: _utils.make_callback(self.__simple_attribute_return, self.__address),
            }
        )

        with contextlib.suppress(OSError):
            set_tcp_nodelay(self.__proxy, True)
        with contextlib.suppress(OSError):
            set_tcp_keepalive(self.__proxy, True)

    def __repr__(self) -> str:
        return f"<client with address {self.__address} at {id(self):#x}>"

    @override
    def is_closing(self) -> bool:
        return self.__closing.is_set()

    def _on_disconnect(self) -> None:
        self.__closing.set()
        with self.__send_lock:  # If self.send_packet() took the lock, wait for it to finish
            pass

    @override
    def abort(self) -> None:
        with self.__send_lock:
            self.__closing.set()
            self.__client.abort()

    @override
    def close(self) -> None:
        with self.__send_lock:
            self.__closing.set()
            self.__client.close()

    @override
    def send_packet(self, packet: Response, /, *, timeout: float | None = None) -> None:
        with self.__send_lock:
            if self.__closing.is_set():
                raise ClientClosedError("Closed client")
            self.__client.send_packet(packet, timeout=timeout)

    @staticmethod
    def __simple_attribute_return[T](value: T) -> T:
        return value

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__extra_attributes_cache
