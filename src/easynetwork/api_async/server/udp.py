# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Asynchronous network server module"""

from __future__ import annotations

__all__ = ["AsyncUDPNetworkServer"]

import contextlib as _contextlib
import logging as _logging
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Generic, Literal, Mapping, TypeVar, final

from ...exceptions import ClientClosedError, DatagramProtocolParseError
from ...protocol import DatagramProtocol
from ...tools._utils import check_real_socket_state as _check_real_socket_state
from ...tools.socket import SocketAddress, SocketProxy, new_socket_address
from ..backend.factory import AsyncBackendFactory
from ..backend.tasks import SingleTaskRunner
from .abc import AbstractAsyncNetworkServer
from .handler import AsyncBaseRequestHandler, AsyncClientInterface, AsyncDatagramRequestHandler

if TYPE_CHECKING:
    from ..backend.abc import AbstractAsyncBackend, AbstractAsyncDatagramSocketAdapter, AbstractTask, AbstractTaskGroup, ILock


_RequestT = TypeVar("_RequestT")
_ResponseT = TypeVar("_ResponseT")


class AsyncUDPNetworkServer(AbstractAsyncNetworkServer, Generic[_RequestT, _ResponseT]):
    __slots__ = (
        "__backend",
        "__socket",
        "__socket_factory",
        "__protocol",
        "__request_handler",
        "__is_up",
        "__is_shutdown",
        "__shutdown_asked",
        "__sendto_lock",
        "__mainloop_task",
        "__service_actions_interval",
        "__logger",
    )

    def __init__(
        self,
        host: str | None,
        port: int,
        protocol: DatagramProtocol[_ResponseT, _RequestT],
        request_handler: AsyncBaseRequestHandler[_RequestT, _ResponseT],
        *,
        family: int = 0,
        reuse_port: bool = False,
        backend: str | AbstractAsyncBackend | None = None,
        backend_kwargs: Mapping[str, Any] | None = None,
        service_actions_interval: float = 0.1,
        logger: _logging.Logger | None = None,
    ) -> None:
        super().__init__()

        backend = AsyncBackendFactory.ensure(backend, backend_kwargs)

        assert isinstance(protocol, DatagramProtocol)

        self.__socket_factory: SingleTaskRunner[AbstractAsyncDatagramSocketAdapter] | None
        self.__socket_factory = SingleTaskRunner(
            backend,
            backend.create_udp_endpoint,
            local_address=(host, port),
            remote_address=None,
            family=family,
            reuse_port=reuse_port,
        )

        self.__service_actions_interval: float = max(service_actions_interval, 0)
        self.__backend: AbstractAsyncBackend = backend
        self.__socket: AbstractAsyncDatagramSocketAdapter | None = None
        self.__protocol: DatagramProtocol[_ResponseT, _RequestT] = protocol
        self.__request_handler: AsyncBaseRequestHandler[_RequestT, _ResponseT] = request_handler
        self.__is_up = self.__backend.create_event()
        self.__is_shutdown = self.__backend.create_event()
        self.__is_shutdown.set()
        self.__shutdown_asked: bool = False
        self.__sendto_lock: ILock = backend.create_lock()
        self.__mainloop_task: AbstractTask[None] | None = None
        self.__logger: _logging.Logger = logger or _logging.getLogger(__name__)

    def is_serving(self) -> bool:
        return self.__socket is not None

    async def wait_for_server_to_be_up(self) -> Literal[True]:
        if not self.__is_up.is_set():
            if self.__socket is None and self.__socket_factory is None:
                raise RuntimeError("Closed server")
            await self.__is_up.wait()
        return True

    async def server_close(self) -> None:
        if self.__socket_factory is not None:
            self.__socket_factory.cancel()
            self.__socket_factory = None
        if self.__mainloop_task is not None:
            self.__mainloop_task.cancel()
            self.__mainloop_task = None
            await self.__backend.coro_yield()
        socket, self.__socket = self.__socket, None
        if socket is None:
            return
        async with _contextlib.AsyncExitStack() as exit_stack:
            exit_stack.push_async_callback(socket.abort)
            exit_stack.push_async_callback(socket.aclose)

    async def shutdown(self) -> None:
        if self.__mainloop_task is not None:
            self.__mainloop_task.cancel()
            self.__mainloop_task = None
        self.__shutdown_asked = True
        try:
            await self.__is_shutdown.wait()
        finally:
            self.__shutdown_asked = False

    async def serve_forever(self) -> None:
        if not self.__is_shutdown.is_set():
            raise RuntimeError("Server is already running")

        async with _contextlib.AsyncExitStack() as server_exit_stack:
            # Wake up server
            self.__is_shutdown.clear()
            server_exit_stack.callback(self.__is_shutdown.set)
            ################

            # Bind and activate
            assert self.__socket is None
            if self.__socket_factory is None:
                raise RuntimeError("Closed server")
            self.__socket = await self.__socket_factory.run()
            self.__socket_factory = None
            ###################

            # Final teardown
            server_exit_stack.callback(self.__logger.info, "Server stopped")
            server_exit_stack.push_async_callback(self.server_close)
            ###########

            # Initialize request handler
            await self.__request_handler.service_init(self.__backend)
            server_exit_stack.push_async_callback(self.__request_handler.service_quit)
            ############################

            # Setup task group
            task_group: AbstractTaskGroup = await server_exit_stack.enter_async_context(self.__backend.create_task_group())
            server_exit_stack.callback(self.__logger.info, "Server loop break, waiting for remaining tasks...")
            ##################

            # Enable socket
            address: SocketAddress = new_socket_address(self.__socket.get_local_address(), self.__socket.socket().family)
            self.__logger.info("Start serving at %s", address)
            del address
            #################

            # Server is up
            self.__is_up.set()
            server_exit_stack.callback(self.__is_up.clear)
            task_group.start_soon(self.__service_actions_task)
            ##############

            # Main loop
            self.__mainloop_task = task_group.start_soon(self.__receive_datagrams_task, self.__socket, task_group)
            if self.__shutdown_asked:
                await self.__backend.coro_yield()
                self.__mainloop_task.cancel()
            try:
                await self.__mainloop_task.join()
            finally:
                self.__mainloop_task = None

    async def __receive_datagrams_task(
        self,
        socket: AbstractAsyncDatagramSocketAdapter,
        task_group: AbstractTaskGroup,
    ) -> None:
        socket_family: int = socket.socket().family
        accept_request_from: Callable[[SocketAddress], Awaitable[bool]] | None = None
        if isinstance(self.__request_handler, AsyncDatagramRequestHandler):
            accept_request_from = self.__request_handler.accept_request_from
        datagram_received_task = self.__datagram_received_task
        while not socket.is_closing():
            datagram, client_address = await socket.recvfrom()
            client_address = new_socket_address(client_address, socket_family)
            self.__logger.debug("Received a datagram from %s", client_address)
            if accept_request_from is None or await accept_request_from(client_address):
                task_group.start_soon(datagram_received_task, socket, datagram, client_address)
            else:
                self.__logger.warning("A datagram from %s has been refused", client_address)
            del datagram, client_address

    async def __service_actions_task(self) -> None:
        request_handler = self.__request_handler
        backend = self.__backend
        while True:
            try:
                await request_handler.service_actions()
            except Exception:
                self.__logger.exception("Error occurred in request_handler.service_actions()")
            await backend.sleep(self.__service_actions_interval)

    async def __datagram_received_task(
        self,
        socket: AbstractAsyncDatagramSocketAdapter,
        datagram: bytes,
        client_address: SocketAddress,
    ) -> None:
        request_handler: AsyncBaseRequestHandler[_RequestT, _ResponseT] = self.__request_handler

        async with _contextlib.aclosing(
            _ClientAPI(
                self.__backend,
                client_address,
                socket,
                self.__protocol,
                self.__sendto_lock,
                self.__logger,
            )
        ) as client:
            try:
                try:
                    request: _RequestT = self.__protocol.build_packet_from_datagram(datagram)
                except DatagramProtocolParseError as exc:
                    self.__logger.debug("Malformed request sent by %s", client.address)
                    await request_handler.bad_request(client, exc.with_traceback(None))
                    return
                finally:
                    del datagram

                self.__logger.debug("Processing request sent by %s", client.address)
                await request_handler.handle(request, client)
            except OSError as exc:
                try:
                    await client.aclose()
                finally:
                    await self.__handle_error(client, exc)
            except Exception as exc:
                await self.__handle_error(client, exc)

    async def __handle_error(self, client: _ClientAPI[_ResponseT], exc: Exception) -> None:
        try:
            request_handler = self.__request_handler
            assert isinstance(client, _ClientAPI)
            if await request_handler.handle_error(client, exc):
                return

            self.__logger.error("-" * 40)
            self.__logger.error("Exception occurred during processing of request from %s", client.address, exc_info=exc)
            self.__logger.error("-" * 40)
        finally:
            del exc

    def get_backend(self) -> AbstractAsyncBackend:
        return self.__backend

    def get_protocol(self) -> DatagramProtocol[_ResponseT, _RequestT]:
        return self.__protocol

    @property
    def socket(self) -> SocketProxy | None:
        if (socket := self.__socket) is None:
            return None
        return SocketProxy(socket.socket())

    @property
    def logger(self) -> _logging.Logger:
        return self.__logger


@final
class _ClientAPI(AsyncClientInterface[_ResponseT]):
    __slots__ = (
        "__backend",
        "__socket_ref",
        "__socket_proxy",
        "__protocol",
        "__lock",
        "__h",
        "__logger",
    )

    def __init__(
        self,
        backend: AbstractAsyncBackend,
        address: SocketAddress,
        socket: AbstractAsyncDatagramSocketAdapter,
        protocol: DatagramProtocol[_ResponseT, Any],
        lock: ILock,
        logger: _logging.Logger,
    ) -> None:
        super().__init__(address)

        import weakref

        self.__backend: AbstractAsyncBackend = backend
        self.__socket_ref: Callable[[], AbstractAsyncDatagramSocketAdapter | None] = weakref.ref(socket)
        self.__socket_proxy: SocketProxy = SocketProxy(socket.socket())
        self.__h: int | None = None
        self.__protocol: DatagramProtocol[_ResponseT, Any] = protocol
        self.__lock: ILock = lock
        self.__logger: _logging.Logger = logger

    def __hash__(self) -> int:
        if (h := self.__h) is None:
            self.__h = h = hash((_ClientAPI, self.address, 0xFF))
        return h

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _ClientAPI):
            return NotImplemented
        return self.address == other.address

    def is_closing(self) -> bool:
        return self.__socket_ref() is None

    async def aclose(self) -> None:
        self.__socket_ref = lambda: None
        await self.__backend.coro_yield()

    async def send_packet(self, packet: _ResponseT, /) -> None:
        async with self.__lock:
            socket = self.__socket_ref()
            if socket is None:
                raise ClientClosedError("Closed client")
            datagram: bytes = self.__protocol.make_datagram(packet)
            self.__logger.debug("A datagram will be sent to %s", self.address)
            try:
                await socket.sendto(datagram, self.address)
                _check_real_socket_state(self.socket)
                self.__logger.debug("Datagram successfully sent to %s.", self.address)
            finally:
                del datagram

    @property
    def socket(self) -> SocketProxy:
        return self.__socket_proxy
