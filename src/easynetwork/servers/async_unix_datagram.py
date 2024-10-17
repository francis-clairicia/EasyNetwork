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
"""Asynchronous Unix datagram server implementation module.

.. versionadded:: 1.1
"""

from __future__ import annotations

__all__ = ["AsyncUnixDatagramServer"]

import contextlib
import errno as _errno
import functools
import logging
import os
import pathlib
import weakref
from collections.abc import Callable, Coroutine, Mapping, Sequence
from types import TracebackType
from typing import Any, Generic, Literal, NoReturn, TypeAlias, assert_never, final

from .._typevars import _T_Request, _T_Response
from ..exceptions import ClientClosedError
from ..lowlevel import _unix_utils, _utils
from ..lowlevel._final import runtime_final_class
from ..lowlevel.api_async.backend.abc import AsyncBackend, TaskGroup
from ..lowlevel.api_async.backend.utils import BuiltinAsyncBackendLiteral
from ..lowlevel.api_async.servers import datagram as _datagram_server
from ..lowlevel.api_async.transports.abc import AsyncDatagramListener
from ..lowlevel.socket import SocketProxy, UnixSocketAddress, UNIXSocketAttribute
from ..protocol import DatagramProtocol
from . import _base
from .handlers import AsyncDatagramClient, AsyncDatagramRequestHandler, UNIXClientAttribute
from .misc import build_lowlevel_datagram_server_handler

_UnnamedAddressesBehavior = Literal["ignore", "handle", "warn"]


class AsyncUnixDatagramServer(
    _base.BaseAsyncNetworkServerImpl[
        _datagram_server.AsyncDatagramServer[_T_Request, _T_Response, UnixSocketAddress],
        UnixSocketAddress,
    ],
    Generic[_T_Request, _T_Response],
):
    """
    An asynchronous Unix datagram server.

    .. versionadded:: 1.1
    """

    __slots__ = (
        "__listener_factory",
        "__protocol",
        "__request_handler",
        "__service_available",
        "__unix_socket_to_delete",
        "__unnamed_addresses_behavior",
    )

    def __init__(
        self,
        path: str | os.PathLike[str] | bytes | UnixSocketAddress,
        protocol: DatagramProtocol[_T_Response, _T_Request],
        request_handler: AsyncDatagramRequestHandler[_T_Request, _T_Response],
        backend: AsyncBackend | BuiltinAsyncBackendLiteral | None = None,
        *,
        mode: int | None = None,
        unnamed_addresses_behavior: _UnnamedAddressesBehavior | None = None,
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
            logger: If given, the logger instance to use.
        """
        super().__init__(
            backend=backend,
            servers_factory=_utils.weak_method_proxy(self.__activate_listeners),
            initialize_service=_utils.weak_method_proxy(self.__initialize_service),
            lowlevel_serve=_utils.weak_method_proxy(self.__lowlevel_serve),
            logger=logger or logging.getLogger(__name__),
        )

        path = _unix_utils.convert_unix_socket_address(path)

        if not isinstance(protocol, DatagramProtocol):
            raise TypeError(f"Expected a DatagramProtocol object, got {protocol!r}")
        if not isinstance(request_handler, AsyncDatagramRequestHandler):
            raise TypeError(f"Expected an AsyncDatagramRequestHandler object, got {request_handler!r}")

        backend = self.backend()

        match unnamed_addresses_behavior:
            case None:
                unnamed_addresses_behavior = "ignore"
            case "handle" | "ignore" | "warn":
                pass
            case _:
                raise ValueError(f"Invalid unnamed_addresses_behavior value, got {unnamed_addresses_behavior!r}")

        self.__listener_factory: Callable[[], Coroutine[Any, Any, AsyncDatagramListener[str | bytes]]]
        self.__listener_factory = _utils.make_callback(
            backend.create_unix_datagram_listener,
            path,
            mode=mode,
        )

        self.__protocol: DatagramProtocol[_T_Response, _T_Request] = protocol
        self.__request_handler: AsyncDatagramRequestHandler[_T_Request, _T_Response] = request_handler
        self.__service_available = _utils.Flag()
        self.__unix_socket_to_delete: dict[pathlib.Path, int] = {}
        self.__unnamed_addresses_behavior = unnamed_addresses_behavior

    async def server_close(self) -> None:
        unix_socket_to_delete = self.__unix_socket_to_delete
        self.__unix_socket_to_delete = {}
        try:
            await super().server_close()
        except self.backend().get_cancelled_exc_class():
            if unix_socket_to_delete:
                await self.backend().run_in_thread(self.__cleanup_unix_socket, unix_socket_to_delete, self.logger)
            raise
        else:
            if unix_socket_to_delete:
                await self.backend().run_in_thread(self.__cleanup_unix_socket, unix_socket_to_delete, self.logger)

    @staticmethod
    def __cleanup_unix_socket(unix_socket_to_delete: dict[pathlib.Path, int], logger: logging.Logger) -> None:
        while unix_socket_to_delete:
            path, prev_ino = unix_socket_to_delete.popitem()
            try:
                if os.stat(path).st_ino == prev_ino:
                    os.unlink(path)
            except FileNotFoundError:
                pass
            except OSError as exc:
                logger.error("Unable to clean up listening Unix socket %r: %s", os.fspath(path), exc)

    async def __activate_listeners(
        self,
    ) -> list[_datagram_server.AsyncDatagramServer[_T_Request, _T_Response, UnixSocketAddress]]:
        listener = await self.__listener_factory()

        local_name = UnixSocketAddress.from_raw(listener.extra(UNIXSocketAttribute.sockname))
        if (path := local_name.as_pathname()) is not None:
            self.__unix_socket_to_delete[path] = os.stat(path).st_ino

        server = _datagram_server.AsyncDatagramServer(_UnixDatagramListener(listener), self.__protocol)
        return [server]

    async def __initialize_service(self, server_exit_stack: contextlib.AsyncExitStack) -> None:
        await self.__request_handler.service_init(
            await server_exit_stack.enter_async_context(contextlib.AsyncExitStack()),
            weakref.proxy(self),
        )

        self.__service_available.set()
        server_exit_stack.callback(self.__service_available.clear)

    async def __lowlevel_serve(
        self,
        server: _datagram_server.AsyncDatagramServer[_T_Request, _T_Response, UnixSocketAddress],
        task_group: TaskGroup,
    ) -> NoReturn:
        handler = build_lowlevel_datagram_server_handler(
            self.__client_initializer,
            self.__request_handler,
            weakref.WeakValueDictionary(),
        )
        await server.serve(handler, task_group)

    def __client_initializer(
        self,
        lowlevel_client: _datagram_server.DatagramClientContext[_T_Response, UnixSocketAddress],
        client_cache: _ClientCacheDictType[_T_Response],
    ) -> _ClientContext[_T_Response]:
        return _ClientContext(
            lowlevel_client=lowlevel_client,
            client_cache=client_cache,
            service_available=self.__service_available,
            unnamed_addresses_behavior=self.__unnamed_addresses_behavior,
            logger=self.logger,
        )

    @_utils.inherit_doc(_base.BaseAsyncNetworkServerImpl)
    def get_addresses(self) -> Sequence[UnixSocketAddress]:
        return self._with_lowlevel_servers(
            lambda servers: tuple(
                UnixSocketAddress.from_raw(server.extra(UNIXSocketAttribute.sockname))
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
            lambda servers: tuple(SocketProxy(server.extra(UNIXSocketAttribute.socket)) for server in servers)
        )


@final
@runtime_final_class
class _UnixDatagramListener(AsyncDatagramListener[UnixSocketAddress]):
    __slots__ = ("__wrapped",)

    def __init__(self, wrapped: AsyncDatagramListener[str | bytes]) -> None:
        self.__wrapped: AsyncDatagramListener[str | bytes] = wrapped

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.__wrapped!r})"

    def is_closing(self) -> bool:
        return self.__wrapped.is_closing()

    async def aclose(self) -> None:
        return await self.__wrapped.aclose()

    async def serve(
        self,
        handler: Callable[[bytes, UnixSocketAddress], Coroutine[Any, Any, None]],
        task_group: TaskGroup | None = None,
    ) -> NoReturn:

        @functools.wraps(handler, assigned=())
        def wrapper(datagram: bytes, addr: str | bytes | None) -> Coroutine[Any, Any, None]:
            if addr is None:
                # A datagram received from an unnamed Unix datagram socket have a "None" address.
                # https://github.com/python/cpython/blob/v3.11.10/Modules/socketmodule.c#L1321-L1324
                return handler(datagram, UnixSocketAddress())
            else:
                return handler(datagram, UnixSocketAddress.from_raw(addr))

        await self.__wrapped.serve(wrapper, task_group)

    async def send_to(self, data: bytes | bytearray | memoryview, address: UnixSocketAddress) -> None:
        if address.is_unnamed():
            raise OSError(_errno.EINVAL, "Cannot send a datagram to an unnamed address.")
        return await self.__wrapped.send_to(data, address.as_raw())

    def backend(self) -> AsyncBackend:
        return self.__wrapped.backend()

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__wrapped.extra_attributes


@final
@runtime_final_class
class _ClientAPI(AsyncDatagramClient[_T_Response]):
    __slots__ = (
        "__context",
        "__service_available",
        "__h",
    )

    def __init__(
        self,
        context: _datagram_server.DatagramClientContext[_T_Response, UnixSocketAddress],
        service_available: _utils.Flag,
    ) -> None:
        super().__init__()
        self.__context: _datagram_server.DatagramClientContext[_T_Response, UnixSocketAddress] = context
        self.__h: int | None = None
        self.__service_available: _utils.Flag = service_available

    def __repr__(self) -> str:
        return f"<client with address {self.__context.address} at {id(self):#x}>"

    def __hash__(self) -> int:
        if (h := self.__h) is None:
            self.__h = h = hash(self.__context)
        return h

    def __eq__(self, other: object) -> bool:
        match other:
            case _ClientAPI():
                return self.__context == other.__context
            case _:
                return NotImplemented

    def is_closing(self) -> bool:
        return self.__is_closing(self.__service_available, self.__context.server)

    @staticmethod
    def __is_closing(
        service_available: _utils.Flag,
        server: _datagram_server.AsyncDatagramServer[Any, _T_Response, UnixSocketAddress],
    ) -> bool:
        return (not service_available.is_set()) or server.is_closing()

    async def send_packet(self, packet: _T_Response, /) -> None:
        server = self.__context.server
        address = self.__context.address
        if self.__is_closing(self.__service_available, server):
            raise ClientClosedError("Closed client")
        await server.send_packet_to(packet, address)

    def backend(self) -> AsyncBackend:
        return self.__context.backend()

    def __get_server_socket(self) -> SocketProxy:
        server = self.__context.server
        return SocketProxy(server.extra(UNIXSocketAttribute.socket))

    def __get_server_address(self) -> UnixSocketAddress:
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


_ClientCacheDictType: TypeAlias = weakref.WeakValueDictionary[
    _datagram_server.DatagramClientContext[_T_Response, UnixSocketAddress],
    _ClientAPI[_T_Response],
]


@final
@runtime_final_class
class _ClientContext(Generic[_T_Response]):
    __slots__ = (
        "__lowlevel_client",
        "__client_cache",
        "__service_available",
        "__unnamed_addresses_behavior",
        "__logger",
    )

    def __init__(
        self,
        lowlevel_client: _datagram_server.DatagramClientContext[_T_Response, UnixSocketAddress],
        client_cache: _ClientCacheDictType[_T_Response],
        service_available: _utils.Flag,
        unnamed_addresses_behavior: _UnnamedAddressesBehavior,
        logger: logging.Logger,
    ) -> None:
        self.__lowlevel_client: _datagram_server.DatagramClientContext[_T_Response, UnixSocketAddress] = lowlevel_client
        self.__client_cache: _ClientCacheDictType[_T_Response] = client_cache
        self.__service_available: _utils.Flag = service_available
        self.__logger: logging.Logger = logger
        self.__unnamed_addresses_behavior: _UnnamedAddressesBehavior = unnamed_addresses_behavior

    async def __aenter__(self) -> AsyncDatagramClient[_T_Response] | None:
        lowlevel_client = self.__lowlevel_client
        if lowlevel_client.address.is_unnamed():
            match self.__unnamed_addresses_behavior:
                case "ignore":
                    return None
                case "warn":
                    self.__logger.warning("A datagram received from an unbound UNIX datagram socket was dropped.")
                    return None
                case "handle":
                    # Do not store an unnamed client in cache.
                    return _ClientAPI(lowlevel_client, self.__service_available)
                case _:  # pragma: no cover
                    assert_never(self.__unnamed_addresses_behavior)
        try:
            client = self.__client_cache[lowlevel_client]
        except KeyError:
            self.__client_cache[lowlevel_client] = client = _ClientAPI(lowlevel_client, self.__service_available)
        return client

    async def __aexit__(
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
        error_handler = _base.ClientErrorHandler(logger=self.__logger, client_address_cb=client_address_cb, suppress_errors=())
        try:
            return error_handler.__exit__(exc_type, exc_val, exc_tb)
        finally:
            exc_type = exc_val = exc_tb = None
