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
"""Asynchronous UDP Network client implementation module."""

from __future__ import annotations

__all__ = ["AsyncUDPNetworkServer"]

import contextlib
import logging
import types
import weakref
from collections.abc import Callable, Coroutine, Mapping, Sequence
from typing import Any, Generic, NoReturn, final

from .._typevars import _T_Request, _T_Response
from ..exceptions import ClientClosedError
from ..lowlevel import _utils
from ..lowlevel._final import runtime_final_class
from ..lowlevel.api_async.backend.abc import AsyncBackend, TaskGroup
from ..lowlevel.api_async.backend.utils import BuiltinAsyncBackendLiteral
from ..lowlevel.api_async.servers import datagram as _datagram_server
from ..lowlevel.api_async.transports.abc import AsyncDatagramListener
from ..lowlevel.socket import INETSocketAttribute, SocketAddress, SocketProxy, new_socket_address
from ..protocol import DatagramProtocol
from . import _base
from .handlers import AsyncDatagramClient, AsyncDatagramRequestHandler, INETClientAttribute
from .misc import build_lowlevel_datagram_server_handler


class AsyncUDPNetworkServer(
    _base.BaseAsyncNetworkServerImpl[
        _datagram_server.AsyncDatagramServer[_T_Request, _T_Response, tuple[Any, ...]],
        SocketAddress,
    ],
    Generic[_T_Request, _T_Response],
):
    """
    An asynchronous network server for UDP communication.
    """

    __slots__ = (
        "__listeners_factory",
        "__protocol",
        "__request_handler",
        "__service_available",
    )

    def __init__(
        self,
        host: str | None | Sequence[str],
        port: int,
        protocol: DatagramProtocol[_T_Response, _T_Request],
        request_handler: AsyncDatagramRequestHandler[_T_Request, _T_Response],
        backend: AsyncBackend | BuiltinAsyncBackendLiteral | None = None,
        *,
        reuse_port: bool = False,
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
            backend: The :term:`asynchronous backend interface` to use.

        Keyword Arguments:
            reuse_port: tells the kernel to allow this endpoint to be bound to the same port as other existing endpoints
                        are bound to, so long as they all set this flag when being created.
                        This option is not supported on Windows.
            logger: If given, the logger instance to use.
        """
        super().__init__(
            backend=backend,
            servers_factory=type(self).__activate_listeners,
            initialize_service=type(self).__initialize_service,
            lowlevel_serve=type(self).__lowlevel_serve,
            logger=logger or logging.getLogger(__name__),
        )

        if not isinstance(protocol, DatagramProtocol):
            raise TypeError(f"Expected a DatagramProtocol object, got {protocol!r}")
        if not isinstance(request_handler, AsyncDatagramRequestHandler):
            raise TypeError(f"Expected an AsyncDatagramRequestHandler object, got {request_handler!r}")

        backend = self.backend()

        self.__listeners_factory: Callable[[], Coroutine[Any, Any, Sequence[AsyncDatagramListener[tuple[Any, ...]]]]]
        self.__listeners_factory = _utils.make_callback(
            backend.create_udp_listeners,
            host,
            port,
            reuse_port=reuse_port,
        )

        self.__protocol: DatagramProtocol[_T_Response, _T_Request] = protocol
        self.__request_handler: AsyncDatagramRequestHandler[_T_Request, _T_Response] = request_handler
        self.__service_available = _utils.Flag()

    async def __activate_listeners(self) -> list[_datagram_server.AsyncDatagramServer[_T_Request, _T_Response, tuple[Any, ...]]]:
        return [
            _datagram_server.AsyncDatagramServer(
                listener,
                self.__protocol,
            )
            for listener in await self.__listeners_factory()
        ]

    async def __initialize_service(self, server_exit_stack: contextlib.AsyncExitStack) -> None:
        await self.__request_handler.service_init(
            await server_exit_stack.enter_async_context(contextlib.AsyncExitStack()),
            weakref.proxy(self),
        )

        self.__service_available.set()
        server_exit_stack.callback(self.__service_available.clear)

    async def __lowlevel_serve(
        self,
        server: _datagram_server.AsyncDatagramServer[_T_Request, _T_Response, tuple[Any, ...]],
        task_group: TaskGroup,
    ) -> NoReturn:
        handler = build_lowlevel_datagram_server_handler(self.__client_initializer, self.__request_handler)
        await server.serve(handler, task_group)

    def __client_initializer(
        self,
        lowlevel_client: _datagram_server.DatagramClientContext[_T_Response, tuple[Any, ...]],
    ) -> _ClientContext:
        return _ClientContext(lowlevel_client, self.__service_available, self.logger)

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
class _ClientAPI(AsyncDatagramClient[_T_Response]):
    __slots__ = (
        "__context",
        "__service_available",
        "__h",
        "__extra_attributes_cache",
    )

    def __init__(
        self,
        context: _datagram_server.DatagramClientContext[_T_Response, tuple[Any, ...]],
        service_available: _utils.Flag,
    ) -> None:
        super().__init__()
        self.__context: _datagram_server.DatagramClientContext[_T_Response, tuple[Any, ...]] = context
        self.__h: int | None = None
        self.__extra_attributes_cache: Mapping[Any, Callable[[], Any]] | None = None
        self.__service_available: _utils.Flag = service_available

    def __repr__(self) -> str:
        return f"<client with address {self.__context.address} at {id(self):#x}>"

    def __hash__(self) -> int:
        if (h := self.__h) is None:
            self.__h = h = hash(self.__context)
        return h

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _ClientAPI):
            return NotImplemented
        return self.__context == other.__context

    def is_closing(self) -> bool:
        return self.__is_closing(self.__service_available, self.__context.server)

    @staticmethod
    def __is_closing(
        service_available: _utils.Flag,
        server: _datagram_server.AsyncDatagramServer[Any, _T_Response, tuple[Any, ...]],
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

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        if (extra_attributes_cache := self.__extra_attributes_cache) is not None:
            return extra_attributes_cache
        server = self.__context.server
        self.__extra_attributes_cache = extra_attributes_cache = {
            **server.extra_attributes,
            INETClientAttribute.socket: lambda: SocketProxy(server.extra(INETSocketAttribute.socket)),
            INETClientAttribute.local_address: lambda: new_socket_address(
                server.extra(INETSocketAttribute.sockname),
                server.extra(INETSocketAttribute.family),
            ),
            INETClientAttribute.remote_address: lambda: new_socket_address(
                self.__context.address,
                server.extra(INETSocketAttribute.family),
            ),
        }
        return extra_attributes_cache


@final
@runtime_final_class
class _ClientContext:
    __slots__ = (
        "__lowlevel_client",
        "__service_available",
        "__logger",
    )

    def __init__(
        self,
        lowlevel_client: _datagram_server.DatagramClientContext[Any, tuple[Any, ...]],
        service_available: _utils.Flag,
        logger: logging.Logger,
    ) -> None:
        self.__lowlevel_client: _datagram_server.DatagramClientContext[Any, tuple[Any, ...]] = lowlevel_client
        self.__service_available: _utils.Flag = service_available
        self.__logger: logging.Logger = logger

    async def __aenter__(self) -> AsyncDatagramClient[_T_Response]:
        return _ClientAPI(self.__lowlevel_client, self.__service_available)

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
        /,
    ) -> bool:
        # Fast path.
        if exc_val is None:
            return False

        del exc_type, exc_tb

        try:
            match exc_val:
                case BaseExceptionGroup():
                    connection_errors, exc_val = exc_val.split(ClientClosedError)
                    if connection_errors is not None:
                        self.__log_closed_client_errors(connection_errors)
                    match exc_val:
                        case None:
                            return True
                        case Exception():
                            self.__log_exception(exc_val)
                            return True
                        case _:  # pragma: no cover
                            del connection_errors
                            raise exc_val
                case ClientClosedError():
                    self.__log_closed_client_errors(ExceptionGroup("", [exc_val]))
                    return True
                case Exception():
                    self.__log_exception(exc_val)
                    return True
                case _:
                    return False
        finally:
            del exc_val

    def __log_closed_client_errors(self, exc: ExceptionGroup[ClientClosedError]) -> None:
        lowlevel_client = self.__lowlevel_client
        self.__logger.warning(
            "There have been attempts to do operation on closed client %s",
            new_socket_address(lowlevel_client.address, lowlevel_client.server.extra(INETSocketAttribute.family)),
            exc_info=exc,
        )

    def __log_exception(self, exc: Exception) -> None:
        lowlevel_client = self.__lowlevel_client
        self.__logger.error("-" * 40)
        self.__logger.error(
            "Exception occurred during processing of request from %s",
            new_socket_address(lowlevel_client.address, lowlevel_client.server.extra(INETSocketAttribute.family)),
            exc_info=exc,
        )
        self.__logger.error("-" * 40)
