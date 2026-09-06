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
"""Multi-threaded UDP Network server implementation module.

.. versionadded:: NEXT_VERSION
"""

from __future__ import annotations

__all__ = ["ThreadedUDPNetworkServer"]

import concurrent.futures
import contextlib
import logging
import socket as _socket
import threading
import weakref
from collections.abc import Callable, Mapping, Sequence
from types import TracebackType
from typing import Any, final, override

from ..exceptions import ClientClosedError
from ..lowlevel import _lock, _utils
from ..lowlevel._final import runtime_final_class
from ..lowlevel.api_sync.servers import selector_datagram as _datagram_server
from ..lowlevel.api_sync.transports.socket import SocketDatagramListener
from ..lowlevel.socket import INETSocketAttribute, SocketAddress, SocketProxy, new_socket_address
from ..protocol import DatagramProtocol
from . import _base
from .handlers import BlockingDatagramClient, BlockingDatagramRequestHandler, INETClientAttribute
from .misc import build_lowlevel_blocking_datagram_server_handler


class ThreadedUDPNetworkServer[Request, Response](
    _base.BaseThreadedNetworkServerImpl[
        _datagram_server.SelectorDatagramServer[Request, Response, tuple[Any, ...]],
        SocketAddress,
    ],
):
    """
    A multi-threaded network server for UDP communication.

    .. versionadded:: NEXT_VERSION
    """

    __slots__ = (
        "__listeners_factory",
        "__protocol",
        "__request_handler",
        "__service_available",
        "__service_close_lock",
    )

    def __init__(
        self,
        host: str | None | Sequence[str],
        port: int,
        protocol: DatagramProtocol[Response, Request],
        request_handler: BlockingDatagramRequestHandler[Request, Response],
        *,
        reuse_port: bool = False,
        max_nb_workers: int | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        """
        Parameters:
            host: specify which network interface to which the server should bind.
            port: specify which port the server should listen on. If the value is ``0``, a random unused port will be selected
                  (note that if `host` resolves to multiple network interfaces, a different random port will be selected
                  for each interface).
            protocol: The :term:`protocol object` to use.
            request_handler: The request handler to use.

        Keyword Arguments:
            reuse_port: Tells the kernel to allow this endpoint to be bound to the same port as other existing
                        endpoints are bound to, so long as they all set this flag when being created.
                        This option is not supported on Windows and some Unixes.
                        If the SO_REUSEPORT constant is not defined then this capability is unsupported.
            max_nb_workers: Use a pool of at most the given value.
            logger: If given, the logger instance to use.
        """
        super().__init__(
            servers_factory=_utils.weak_method_proxy(self.__activate_listeners),
            initialize_service=_utils.weak_method_proxy(self.__initialize_service),
            lowlevel_serve=_utils.weak_method_proxy(self.__lowlevel_serve),
            max_nb_workers=max_nb_workers,
            logger=logger or logging.getLogger(__name__),
        )

        if not isinstance(protocol, DatagramProtocol):
            raise TypeError(f"Expected a DatagramProtocol object, got {protocol!r}")
        if not isinstance(request_handler, BlockingDatagramRequestHandler):
            raise TypeError(f"Expected an BlockingDatagramRequestHandler object, got {request_handler!r}")

        self.__listeners_factory: Callable[[], Sequence[SocketDatagramListener]] = _utils.make_callback(
            self.__create_udp_listeners,
            _utils.validate_listener_hosts(host),
            port,
            reuse_port=reuse_port,
        )

        self.__protocol: DatagramProtocol[Response, Request] = protocol
        self.__request_handler: BlockingDatagramRequestHandler[Request, Response] = request_handler
        self.__service_available = threading.Event()
        self.__service_close_lock = _lock.RWLock()

    @classmethod
    def __create_udp_listeners(
        cls,
        hosts: list[str | None],
        port: int,
        *,
        reuse_port: bool,
    ) -> Sequence[SocketDatagramListener]:
        infos: Sequence[tuple[int, int, int, str, tuple[Any, ...]]] = _base.resolve_listener_addresses(
            hosts,
            port,
            _socket.SOCK_DGRAM,
        )

        sockets: list[_socket.socket] = _utils.open_listener_sockets_from_getaddrinfo_result(
            infos,
            reuse_address=False,
            reuse_port=reuse_port,
        )
        return [SocketDatagramListener(sock) for sock in sockets]

    def __activate_listeners(self) -> list[_datagram_server.SelectorDatagramServer[Request, Response, tuple[Any, ...]]]:
        return [_datagram_server.SelectorDatagramServer(listener, self.__protocol) for listener in self.__listeners_factory()]

    def __initialize_service(self, server_exit_stack: contextlib.ExitStack) -> None:
        self.__request_handler.service_init(
            server_exit_stack.enter_context(contextlib.ExitStack()),
            weakref.proxy(self),
        )

        self.__service_available.set()
        server_exit_stack.callback(self.__service_available.clear)

    def __lowlevel_serve(
        self,
        server: _datagram_server.SelectorDatagramServer[Request, Response, tuple[Any, ...]],
        executor: concurrent.futures.ThreadPoolExecutor,
    ) -> None:
        handler = build_lowlevel_blocking_datagram_server_handler(
            self.__client_initializer,
            self.__request_handler,
            weakref.WeakValueDictionary(),
        )
        server.serve(handler, executor)

    def __client_initializer(
        self,
        lowlevel_client: _datagram_server.DatagramClientContext[Response, tuple[Any, ...]],
        client_cache: _ClientCacheDictType[Response],
    ) -> _ClientContext[Response]:
        return _ClientContext(
            lowlevel_client=lowlevel_client,
            client_cache=client_cache,
            service_available=self.__service_available,
            service_close_lock=self.__service_close_lock,
            logger=self.logger,
        )

    @override
    @_utils.inherit_doc(_base.BaseThreadedNetworkServerImpl)
    def server_close(self) -> None:
        with self.__service_close_lock.write_lock():
            return super().server_close()

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
                SocketProxy(server.extra(INETSocketAttribute.socket), lock=self.__service_close_lock.write_lock)
                for server in servers
            )
        )


@final
@runtime_final_class
class _ClientAPI[Response](BlockingDatagramClient[Response]):
    __slots__ = (
        "__context",
        "__service_available",
        "__service_close_lock",
        "__h",
    )

    def __init__(
        self,
        context: _datagram_server.DatagramClientContext[Response, tuple[Any, ...]],
        service_available: threading.Event,
        service_close_lock: _lock.RWLock,
    ) -> None:
        super().__init__()
        self.__context: _datagram_server.DatagramClientContext[Response, tuple[Any, ...]] = context
        self.__h: int | None = None
        self.__service_available: threading.Event = service_available
        self.__service_close_lock: _lock.RWLock = service_close_lock

    def __repr__(self) -> str:
        return f"<client with address {self.__context.address} at {id(self):#x}>"

    @override
    def __hash__(self) -> int:
        if (h := self.__h) is None:
            self.__h = h = hash(self.__context)
        return h

    @override
    def __eq__(self, other: object) -> bool:
        match other:
            case _ClientAPI():
                return self.__context == other.__context
            case _:
                return NotImplemented

    @override
    def is_closing(self) -> bool:
        return self.__is_closing(self.__service_available, self.__context.server)

    @staticmethod
    def __is_closing(
        service_available: threading.Event,
        server: _datagram_server.SelectorDatagramServer[Any, Response, tuple[Any, ...]],
    ) -> bool:
        return (not service_available.is_set()) or server.is_closed()

    @override
    def send_packet(self, packet: Response, /, *, timeout: float | None = None) -> None:
        server = self.__context.server
        address = self.__context.address
        if self.__is_closing(self.__service_available, server):
            raise ClientClosedError("Closed client")
        server.send_packet_to(packet, address, timeout=timeout)

    def __get_server_socket(self) -> SocketProxy:
        server = self.__context.server
        return SocketProxy(server.extra(INETSocketAttribute.socket), lock=self.__service_close_lock.write_lock)

    def __get_server_address(self) -> SocketAddress:
        with self.__service_close_lock.read_lock():
            server = self.__context.server
            return new_socket_address(server.extra(INETSocketAttribute.sockname), server.extra(INETSocketAttribute.family))

    def __get_remote_address(self) -> SocketAddress:
        with self.__service_close_lock.read_lock():
            server = self.__context.server
            address = self.__context.address
            return new_socket_address(address, server.extra(INETSocketAttribute.family))

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return {
            INETClientAttribute.socket: self.__get_server_socket,
            INETClientAttribute.local_address: self.__get_server_address,
            INETClientAttribute.remote_address: self.__get_remote_address,
            INETSocketAttribute.family: _utils.make_callback(self.__context.server.extra, INETSocketAttribute.family),
        }


type _ClientCacheDictType[Response] = weakref.WeakValueDictionary[
    _datagram_server.DatagramClientContext[Response, tuple[Any, ...]],
    _ClientAPI[Response],
]


@final
@runtime_final_class
class _ClientContext[Response]:
    __slots__ = (
        "__lowlevel_client",
        "__client_cache",
        "__service_available",
        "__service_close_lock",
        "__logger",
    )

    def __init__(
        self,
        *,
        lowlevel_client: _datagram_server.DatagramClientContext[Response, tuple[Any, ...]],
        client_cache: _ClientCacheDictType[Response],
        service_available: threading.Event,
        service_close_lock: _lock.RWLock,
        logger: logging.Logger,
    ) -> None:
        self.__lowlevel_client: _datagram_server.DatagramClientContext[Response, tuple[Any, ...]] = lowlevel_client
        self.__client_cache: _ClientCacheDictType[Response] = client_cache
        self.__service_available: threading.Event = service_available
        self.__logger: logging.Logger = logger
        self.__service_close_lock: _lock.RWLock = service_close_lock

    def __enter__(self) -> BlockingDatagramClient[Response]:
        lowlevel_client = self.__lowlevel_client
        try:
            client = self.__client_cache[lowlevel_client]
        except KeyError:
            self.__client_cache[lowlevel_client] = client = _ClientAPI(
                lowlevel_client,
                self.__service_available,
                self.__service_close_lock,
            )
        return client

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
        /,
    ) -> bool:
        # Fast path.
        if exc_val is None:
            return False

        client_address_cb = self.__client_cache[self.__lowlevel_client].extra_attributes[INETClientAttribute.remote_address]
        error_handler = _base.ClientErrorHandler(logger=self.__logger, client_address_cb=client_address_cb, suppress_errors=())
        try:
            return error_handler.__exit__(exc_type, exc_val, exc_tb)
        finally:
            exc_type = exc_val = exc_tb = None
