# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Asynchronous network server module"""

from __future__ import annotations

__all__ = ["AsyncUDPNetworkServer"]

import contextlib as _contextlib
import logging as _logging
from typing import TYPE_CHECKING, Any, Callable, Generic, Literal, Mapping, Self, TypeVar, final

from ...api_sync.server.handler import BaseRequestHandler
from ...exceptions import ClientClosedError, DatagramProtocolParseError
from ...protocol import DatagramProtocol
from ...tools._utils import check_real_socket_state as _check_real_socket_state
from ...tools.socket import SocketAddress, SocketProxy, new_socket_address
from ..backend.factory import AsyncBackendFactory
from .abc import AbstractAsyncNetworkServer
from .handler import AsyncBaseRequestHandler, AsyncClientInterface, AsyncDatagramRequestHandler

if TYPE_CHECKING:
    from ..backend.abc import AbstractAsyncBackend, AbstractAsyncDatagramSocketAdapter, AbstractTaskGroup


logger = _logging.getLogger(__name__)


_RequestT = TypeVar("_RequestT")
_ResponseT = TypeVar("_ResponseT")


class AsyncUDPNetworkServer(AbstractAsyncNetworkServer, Generic[_RequestT, _ResponseT]):
    __slots__ = (
        "__backend",
        "__socket",
        "__socket_proxy",
        "__address",
        "__protocol",
        "__request_handler",
        "__is_up",
        "__is_shutdown",
        "__sendto_lock",
    )

    def __init__(
        self,
        backend: AbstractAsyncBackend,
        socket: AbstractAsyncDatagramSocketAdapter,
        protocol: DatagramProtocol[_ResponseT, _RequestT],
        request_handler: AsyncBaseRequestHandler[_RequestT, _ResponseT] | BaseRequestHandler[_RequestT, _ResponseT],
    ) -> None:
        super().__init__()

        assert isinstance(protocol, DatagramProtocol)
        if isinstance(request_handler, BaseRequestHandler):
            from .sync_bridge import AsyncDatagramRequestHandlerBridge

            request_handler = AsyncDatagramRequestHandlerBridge(backend, request_handler)

        self.__backend: AbstractAsyncBackend = backend
        self.__socket: AbstractAsyncDatagramSocketAdapter | None = socket
        self.__socket_proxy: SocketProxy = SocketProxy(socket.socket())
        self.__address: SocketAddress = new_socket_address(socket.get_local_address(), socket.socket().family)
        self.__protocol: DatagramProtocol[_ResponseT, _RequestT] = protocol
        self.__request_handler: AsyncBaseRequestHandler[_RequestT, _ResponseT] = request_handler
        self.__is_up = self.__backend.create_event()
        self.__is_shutdown = self.__backend.create_event()
        self.__is_shutdown.set()
        self.__sendto_lock = backend.create_lock()

    @classmethod
    async def create(
        cls,
        host: str | None,
        port: int,
        protocol: DatagramProtocol[_ResponseT, _RequestT],
        request_handler: AsyncBaseRequestHandler[_RequestT, _ResponseT] | BaseRequestHandler[_RequestT, _ResponseT],
        *,
        family: int = 0,
        reuse_port: bool = False,
        backend: str | AbstractAsyncBackend | None = None,
        backend_kwargs: Mapping[str, Any] | None = None,
    ) -> Self:
        backend = AsyncBackendFactory.ensure(backend, backend_kwargs)

        socket = await backend.create_udp_endpoint(
            local_address=(host, port),
            remote_address=None,
            family=family,
            reuse_port=reuse_port,
        )

        return cls(backend, socket, protocol, request_handler)

    def is_serving(self) -> bool:
        return self.__socket is not None and self.__is_up.is_set()

    async def wait_for_server_to_be_up(self) -> Literal[True]:
        if self.__socket is None:
            raise RuntimeError("Closed server")
        await self.__is_up.wait()
        return True

    async def server_close(self) -> None:
        async with self.__sendto_lock:
            socket = self.__socket
            if socket is None:
                return
            self.__socket = None
            try:
                await socket.aclose()
            finally:
                await socket.abort()

    async def serve_forever(self) -> None:
        if (socket := self.__socket) is None:
            raise RuntimeError("Closed server")
        if not self.__is_shutdown.is_set():
            raise RuntimeError("Server is already running")

        async with _contextlib.AsyncExitStack() as server_exit_stack:
            # Final log
            server_exit_stack.callback(logger.info, "Server stopped")
            ###########

            # Wake up server
            self.__is_shutdown.clear()
            server_exit_stack.callback(self.__is_shutdown.set)
            ################

            # Initialize request handler
            await self.__request_handler.service_init()
            server_exit_stack.push_async_callback(self.__request_handler.service_quit)
            ############################

            # Setup task group
            task_group: AbstractTaskGroup = await server_exit_stack.enter_async_context(self.__backend.create_task_group())
            server_exit_stack.callback(logger.info, "Server loop break, waiting for remaining tasks...")
            ##################

            # Enable socket
            logger.info("Start serving at %s", self.__address)
            #################

            # Pull methods to local namespace
            accept_request_from = self.__accept_request_from
            #################################

            # Server is up
            self.__is_up.set()
            server_exit_stack.callback(self.__is_up.clear)
            task_group.start_soon(self.__service_actions_task)
            ##############

            # Main loop
            socket_family: int = self.__socket_proxy.family
            while True:
                try:
                    datagram, client_address = await socket.recvfrom()
                except OSError:
                    logger.exception("socket.recvfrom(): Error occured")
                    return
                client_address = new_socket_address(client_address, socket_family)
                logger.debug("Received a datagram from %s", client_address)
                if await accept_request_from(client_address):
                    task_group.start_soon(self.__datagram_received_task, datagram, client_address)
                else:
                    logger.warning("A datagram from %s was refused", client_address)
                del datagram, client_address

    async def __service_actions_task(self) -> None:
        request_handler = self.__request_handler
        backend = self.__backend
        while True:
            try:
                await request_handler.service_actions()
            except Exception:
                logger.exception("Error occured in request_handler.service_actions()")
            await backend.coro_yield()

    async def __accept_request_from(self, client_address: SocketAddress) -> bool:
        request_handler: AsyncBaseRequestHandler[_RequestT, _ResponseT] = self.__request_handler
        if isinstance(request_handler, AsyncDatagramRequestHandler):
            return await request_handler.accept_request_from(client_address)
        return True

    async def __datagram_received_task(self, datagram: bytes, client_address: SocketAddress) -> None:
        request_handler: AsyncBaseRequestHandler[_RequestT, _ResponseT] = self.__request_handler

        async with _contextlib.aclosing(_ClientAPI(client_address, self)) as client:
            try:
                try:
                    request: _RequestT = self.__protocol.build_packet_from_datagram(datagram)
                except DatagramProtocolParseError as exc:
                    logger.debug("Malformed request sent by %s", client_address)
                    await request_handler.bad_request(client, exc.with_traceback(None))
                    return
                finally:
                    del datagram

                logger.debug("Processing request sent by %s", client_address)
                await request_handler.handle(request, client)
            except OSError as exc:
                try:
                    await client.aclose()
                finally:
                    await self.__handle_error(client, exc)
            except Exception as exc:
                await self.__handle_error(client, exc)

    async def send_packet_to(self, packet: _ResponseT, client_address: SocketAddress) -> None:
        async with self.__sendto_lock:
            socket = self.__socket
            assert socket is not None, "Closed server"
            datagram: bytes = self.__protocol.make_datagram(packet)

            logger.debug("A datagram will be sent to %s", client_address)
            try:
                await socket.sendto(datagram, client_address)
                _check_real_socket_state(self.__socket_proxy)
                logger.debug("Datagram successfully sent to %s.", client_address)
            finally:
                del datagram

    async def __handle_error(self, client: _ClientAPI[_ResponseT], exc: Exception) -> None:
        try:
            request_handler = self.__request_handler
            assert isinstance(client, _ClientAPI)
            if await request_handler.handle_error(client, exc):
                return

            logger.error("-" * 40)
            logger.error("Exception occurred during processing of request from %s", client.address, exc_info=exc)
            logger.error("-" * 40)
        finally:
            del exc

    def get_backend(self) -> AbstractAsyncBackend:
        return self.__backend

    def get_address(self) -> SocketAddress:
        return self.__address

    @property
    def socket(self) -> SocketProxy:
        return self.__socket_proxy


@final
class _ClientAPI(AsyncClientInterface[_ResponseT]):
    __slots__ = ("__server_ref", "__socket_proxy", "__h")

    def __init__(self, address: SocketAddress, server: AsyncUDPNetworkServer[Any, _ResponseT]) -> None:
        super().__init__(address)

        import weakref

        self.__server_ref: Callable[[], AsyncUDPNetworkServer[Any, _ResponseT] | None] = weakref.ref(server)
        self.__socket_proxy: SocketProxy = server.socket
        self.__h: int | None = None

    def __hash__(self) -> int:
        if (h := self.__h) is None:
            self.__h = h = hash((_ClientAPI, self.address, 0xFF))
        return h

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _ClientAPI):
            return NotImplemented
        return self.address == other.address

    def is_closing(self) -> bool:
        return self.__server_ref() is None

    async def aclose(self) -> None:
        self.__server_ref = lambda: None

    async def send_packet(self, packet: _ResponseT) -> None:
        server = self.__server_ref()
        if server is None:
            raise ClientClosedError("Closed client")
        await server.send_packet_to(packet, self.address)

    @property
    def socket(self) -> SocketProxy:
        return self.__socket_proxy
