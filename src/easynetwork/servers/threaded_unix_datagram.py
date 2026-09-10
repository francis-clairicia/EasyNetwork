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
"""Multi-threaded Unix datagram server implementation module.

.. versionadded:: NEXT_VERSION
"""

from __future__ import annotations

__all__: list[str] = []

import socket as _socket
import sys
from typing import TYPE_CHECKING

if sys.platform == "win32" or (not TYPE_CHECKING and not hasattr(_socket, "AF_UNIX")):
    raise ImportError(f"UNIX sockets are not supported on {sys.platform}.")  # pragma: no cover
else:
    # The "else" is necessary for mypy not to check this part...
    # Seems like a big "ImportError" is not enough.

    __all__ += ["ThreadedUnixDatagramServer"]

    import concurrent.futures
    import contextlib
    import errno as _errno
    import logging
    import os
    import threading
    import weakref
    from collections.abc import Buffer, Callable, Iterable, Mapping, Sequence
    from types import TracebackType
    from typing import Any, Literal, assert_never, final, override

    from ..exceptions import ClientClosedError
    from ..lowlevel import _lock, _unix_utils, _utils
    from ..lowlevel._final import runtime_final_class
    from ..lowlevel.api_sync.servers import selector_datagram as _datagram_server
    from ..lowlevel.api_sync.transports.socket import SocketDatagramListener
    from ..lowlevel.socket import SocketAncillary, SocketProxy, UnixSocketAddress, UNIXSocketAttribute
    from ..protocol import DatagramProtocol
    from . import _base
    from .handlers import BlockingDatagramClient, BlockingDatagramRequestHandler, UNIXClientAttribute
    from .misc import build_lowlevel_blocking_datagram_server_handler

    type _UnnamedAddressesBehavior = Literal["ignore", "handle", "warn"]

    class ThreadedUnixDatagramServer[Request, Response](
        _base.BaseThreadedNetworkServerImpl[
            _datagram_server.SelectorDatagramServer[Request, Response, UnixSocketAddress],
            UnixSocketAddress,
        ],
    ):
        """
        A multi-threaded Unix datagram server.

        .. versionadded:: NEXT_VERSION
        """

        __slots__ = (
            "__listener_factory",
            "__protocol",
            "__request_handler",
            "__service_available",
            "__service_close_lock",
            "__unix_socket_to_delete",
            "__unnamed_addresses_behavior",
            "__receive_ancillary_data",
            "__ancillary_bufsize",
        )

        def __init__(
            self,
            path: str | os.PathLike[str] | bytes | UnixSocketAddress,
            protocol: DatagramProtocol[Response, Request],
            request_handler: BlockingDatagramRequestHandler[Request, Response],
            *,
            mode: int | None = None,
            unnamed_addresses_behavior: _UnnamedAddressesBehavior | None = None,
            receive_ancillary_data: bool = False,
            ancillary_bufsize: int | None = None,
            max_nb_workers: int | None = None,
            logger: logging.Logger | None = None,
        ) -> None:
            """
            Parameters:
                path: Path of the socket.
                protocol: The :term:`protocol object` to use.
                request_handler: The request handler to use.
                backend: The :term:`asynchronous backend interface` to use.

            Keyword Arguments:
                mode: Permissions to set on the socket.
                unnamed_addresses_behavior: Defines what to do when receiving datagrams sent from unbound datagram sockets:

                                            * ``"ignore"`` (the default): Silently drop the datagram.

                                            * ``"handle"``: Act as a normal reception.

                                            * ``"warn"``: Drop the datagram and issue a :data:`~logging.WARNING` log.
                receive_ancillary_data: ask the socket to read the ancillary data sent along with a datagram.
                ancillary_bufsize: read buffer size for ancillary data. Defaults to ~8KiB.
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

            path = _unix_utils.convert_unix_socket_address(path)
            if not path and not _unix_utils.platform_supports_automatic_socket_bind():
                msg = "path parameter is required on this platform and cannot be an empty string."
                note = "Automatic socket bind is not supported."
                raise _utils.exception_with_notes(ValueError(msg), note)

            if not isinstance(protocol, DatagramProtocol):
                raise TypeError(f"Expected a DatagramProtocol object, got {protocol!r}")
            if not isinstance(request_handler, BlockingDatagramRequestHandler):
                raise TypeError(f"Expected a BlockingDatagramRequestHandler object, got {request_handler!r}")

            match unnamed_addresses_behavior:
                case None:
                    unnamed_addresses_behavior = "ignore"
                case "handle" | "ignore" | "warn":
                    pass
                case _:
                    raise ValueError(f"Invalid unnamed_addresses_behavior value, got {unnamed_addresses_behavior!r}")

            if not receive_ancillary_data and ancillary_bufsize is not None:
                raise ValueError("ancillary_bufsize is only meaningful with receive_ancillary_data set to True")
            ancillary_bufsize = _base.validate_unix_socket_ancillary_buffer_size(ancillary_bufsize)

            self.__listener_factory: Callable[[], _UnixDatagramListener] = _utils.make_callback(
                self.__create_unix_datagram_listener,
                path,
                mode=mode,
            )

            self.__protocol: DatagramProtocol[Response, Request] = protocol
            self.__request_handler: BlockingDatagramRequestHandler[Request, Response] = request_handler
            self.__service_available = threading.Event()
            self.__service_close_lock = _lock.RWLock()
            self.__unix_socket_to_delete = _base.UnixSocketPathCleaner()
            self.__unnamed_addresses_behavior = unnamed_addresses_behavior
            self.__receive_ancillary_data = receive_ancillary_data
            self.__ancillary_bufsize = ancillary_bufsize

        @classmethod
        def __create_unix_datagram_listener(
            cls,
            path: str | bytes,
            *,
            mode: int | None,
        ) -> _UnixDatagramListener:
            socket = _socket.socket(_socket.AF_UNIX, _socket.SOCK_DGRAM, 0)
            try:
                try:
                    socket.bind(path)
                except OSError as exc:
                    raise _utils.convert_socket_bind_error(exc, path) from None
                if mode is not None:
                    os.chmod(path, mode)
                socket.setblocking(False)
            except BaseException:
                socket.close()
                raise
            return _UnixDatagramListener(socket)

        def __activate_listeners(
            self,
        ) -> list[_datagram_server.SelectorDatagramServer[Request, Response, UnixSocketAddress]]:
            listener = self.__listener_factory()

            local_name = UnixSocketAddress.from_raw(listener.extra(UNIXSocketAttribute.sockname))
            if (path := local_name.as_pathname()) is not None:
                self.__unix_socket_to_delete.register(path)

            server = _datagram_server.SelectorDatagramServer(listener, self.__protocol)
            return [server]

        def __initialize_service(self, server_exit_stack: contextlib.ExitStack) -> None:
            self.__request_handler.service_init(
                server_exit_stack.enter_context(contextlib.ExitStack()),
                weakref.proxy(self),
            )

            self.__service_available.set()
            server_exit_stack.callback(self.__service_available.clear)

        def __lowlevel_serve(
            self,
            server: _datagram_server.SelectorDatagramServer[Request, Response, UnixSocketAddress],
            executor: concurrent.futures.ThreadPoolExecutor,
        ) -> None:
            handler = build_lowlevel_blocking_datagram_server_handler(
                self.__client_initializer,
                self.__request_handler,
                weakref.WeakValueDictionary(),
            )
            if self.__receive_ancillary_data:
                server.serve_with_ancillary(handler, executor, self.__ancillary_bufsize, self.__ancillary_data_unused)
            else:
                server.serve(handler, executor)

        def __ancillary_data_unused(self, raw_ancdata: Any, client_address: UnixSocketAddress, /) -> None:
            if raw_ancdata:
                ancillary = SocketAncillary()
                try:
                    ancillary.update_from_raw(raw_ancdata)
                except Exception as exc:  # pragma: no cover
                    self.logger.warning(f"From {client_address}: Failed to read ancillary data", exc_info=exc)
                finally:
                    _unix_utils.close_fds_in_socket_ancillary(ancillary)

        def __client_initializer(
            self,
            lowlevel_client: _datagram_server.DatagramClientContext[Response, UnixSocketAddress],
            client_cache: _ClientCacheDictType[Response],
        ) -> _ClientContext[Response]:
            return _ClientContext(
                lowlevel_client=lowlevel_client,
                client_cache=client_cache,
                service_available=self.__service_available,
                service_close_lock=self.__service_close_lock,
                unnamed_addresses_behavior=self.__unnamed_addresses_behavior,
                logger=self.logger,
            )

        @override
        @_utils.inherit_doc(_base.BaseThreadedNetworkServerImpl)
        def server_close(self) -> None:
            try:
                with self.__service_close_lock.write_lock():
                    return super().server_close()
            finally:
                self.__unix_socket_to_delete.clean_all(self.logger)

        @override
        @_utils.inherit_doc(_base.BaseThreadedNetworkServerImpl)
        def get_addresses(self) -> Sequence[UnixSocketAddress]:
            return self._with_lowlevel_servers(
                lambda servers: tuple(
                    UnixSocketAddress.from_raw(server.extra(UNIXSocketAttribute.sockname))
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
                    SocketProxy(server.extra(UNIXSocketAttribute.socket), lock=self.__service_close_lock.write_lock)
                    for server in servers
                )
            )

    @final
    @runtime_final_class
    class _UnixDatagramListener(SocketDatagramListener):
        __slots__ = ()

        @override
        @_utils.inherit_doc(SocketDatagramListener)
        def recv_noblock_from(self) -> tuple[bytes, UnixSocketAddress]:
            data, addr = super().recv_noblock_from()
            return data, UnixSocketAddress.from_raw(addr)

        @override
        @_utils.inherit_doc(SocketDatagramListener)
        def recv_noblock_with_ancillary_from(
            self,
            ancillary_bufsize: int,
        ) -> tuple[bytes, list[tuple[int, int, bytes]] | None, Any]:
            data, ancillary, addr = super().recv_noblock_with_ancillary_from(ancillary_bufsize)
            return data, ancillary, UnixSocketAddress.from_raw(addr)

        @override
        @_utils.inherit_doc(SocketDatagramListener)
        def send_noblock_to(self, data: bytes | bytearray | memoryview, address: UnixSocketAddress) -> None:
            if address.is_unnamed():
                raise OSError(_errno.EINVAL, "Cannot send a datagram to an unnamed address.")
            return super().send_noblock_to(data, address.as_raw())

        @override
        @_utils.inherit_doc(SocketDatagramListener)
        def send_noblock_with_ancillary_to(
            self,
            data: bytes | bytearray | memoryview,
            ancillary_data: Iterable[tuple[int, int, Buffer]],
            address: UnixSocketAddress,
        ) -> None:
            if address.is_unnamed():
                raise OSError(_errno.EINVAL, "Cannot send a datagram to an unnamed address.")
            return super().send_noblock_with_ancillary_to(data, ancillary_data, address.as_raw())

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
            context: _datagram_server.DatagramClientContext[Response, UnixSocketAddress],
            service_available: threading.Event,
            service_close_lock: _lock.RWLock,
        ) -> None:
            super().__init__()
            self.__context: _datagram_server.DatagramClientContext[Response, UnixSocketAddress] = context
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
            server: _datagram_server.SelectorDatagramServer[Any, Response, UnixSocketAddress],
        ) -> bool:
            return (not service_available.is_set()) or server.is_closed()

        @override
        def send_packet(self, packet: Response, /, *, timeout: float | None = None) -> None:
            server = self.__context.server
            address = self.__context.address
            if self.__is_closing(self.__service_available, server):
                raise ClientClosedError("Closed client")
            server.send_packet_to(packet, address, timeout=timeout)

        @override
        def send_packet_with_ancillary(self, packet: Response, ancillary_data: Any, *, timeout: float | None = None) -> None:
            if isinstance(ancillary_data, SocketAncillary):
                ancillary_data = ancillary_data.as_raw()
            server = self.__context.server
            address = self.__context.address
            if self.__is_closing(self.__service_available, server):
                raise ClientClosedError("Closed client")
            server.send_packet_with_ancillary_to(packet, ancillary_data, address, timeout=timeout)

        def __get_server_socket(self) -> SocketProxy:
            server = self.__context.server
            return SocketProxy(server.extra(UNIXSocketAttribute.socket), lock=self.__service_close_lock.write_lock)

        def __get_server_address(self) -> UnixSocketAddress:
            with self.__service_close_lock.read_lock():
                server = self.__context.server
                return UnixSocketAddress.from_raw(server.extra(UNIXSocketAttribute.sockname))

        def __get_peer_address(self) -> UnixSocketAddress:
            return self.__context.address

        @property
        def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
            return {
                UNIXClientAttribute.socket: self.__get_server_socket,
                UNIXClientAttribute.local_name: self.__get_server_address,
                UNIXClientAttribute.peer_name: self.__get_peer_address,
                UNIXSocketAttribute.family: _utils.make_callback(self.__context.server.extra, UNIXSocketAttribute.family),
            }

    type _ClientCacheDictType[Response] = weakref.WeakValueDictionary[
        _datagram_server.DatagramClientContext[Response, UnixSocketAddress],
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
            "__unnamed_addresses_behavior",
            "__logger",
        )

        def __init__(
            self,
            lowlevel_client: _datagram_server.DatagramClientContext[Response, UnixSocketAddress],
            client_cache: _ClientCacheDictType[Response],
            service_available: threading.Event,
            service_close_lock: _lock.RWLock,
            unnamed_addresses_behavior: _UnnamedAddressesBehavior,
            logger: logging.Logger,
        ) -> None:
            self.__lowlevel_client: _datagram_server.DatagramClientContext[Response, UnixSocketAddress] = lowlevel_client
            self.__client_cache: _ClientCacheDictType[Response] = client_cache
            self.__service_available: threading.Event = service_available
            self.__service_close_lock: _lock.RWLock = service_close_lock
            self.__logger: logging.Logger = logger
            self.__unnamed_addresses_behavior: _UnnamedAddressesBehavior = unnamed_addresses_behavior

        def __enter__(self) -> BlockingDatagramClient[Response] | None:
            lowlevel_client = self.__lowlevel_client
            if lowlevel_client.address.is_unnamed():
                match self.__unnamed_addresses_behavior:
                    case "ignore":
                        return None
                    case "warn":
                        self.__logger.warning("A datagram received from an unbound UNIX datagram socket has been dropped.")
                        return None
                    case "handle":
                        # Do not store an unnamed client in cache.
                        return _ClientAPI(lowlevel_client, self.__service_available, self.__service_close_lock)
                    case _:  # pragma: no cover
                        assert_never(self.__unnamed_addresses_behavior)
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

            client_address_cb = self.__client_cache[self.__lowlevel_client].extra_attributes[UNIXClientAttribute.peer_name]
            error_handler = _base.ClientErrorHandler(
                logger=self.__logger, client_address_cb=client_address_cb, suppress_errors=()
            )
            try:
                return error_handler.__exit__(exc_type, exc_val, exc_tb)
            finally:
                exc_type = exc_val = exc_tb = None
