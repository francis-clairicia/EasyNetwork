# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""sync-to-async bridge for request handlers"""

from __future__ import annotations

__all__ = [
    "DatagramRequestHandlerAsyncBridge",
    "StreamRequestHandlerAsyncBridge",
]

import contextlib
from abc import abstractmethod
from typing import TYPE_CHECKING, TypeVar, final
from weakref import WeakKeyDictionary

from ...api_sync.server.handler import BaseRequestHandler, ClientInterface, DatagramRequestHandler, StreamRequestHandler
from ...tools.socket import SocketAddress, SocketProxy
from .handler import AsyncBaseRequestHandler, AsyncClientInterface, AsyncDatagramRequestHandler, AsyncStreamRequestHandler

if TYPE_CHECKING:
    from ...exceptions import BaseProtocolParseError
    from ..backend.abc import AbstractAsyncBackend, AbstractAsyncThreadPoolExecutor, AbstractThreadsPortal


_RequestT = TypeVar("_RequestT")
_ResponseT = TypeVar("_ResponseT")


class _BaseAsyncWrapperForRequestHandler(AsyncBaseRequestHandler[_RequestT, _ResponseT]):
    __slots__ = (
        "__backend",
        "__sync_request_handler",
        "__thread_pool_size",
        "__request_thread_pool",
    )

    def __init__(
        self,
        sync_request_handler: BaseRequestHandler[_RequestT, _ResponseT],
        thread_pool_size: int | None = None,
    ) -> None:
        super().__init__()

        self.__backend: AbstractAsyncBackend | None = None
        self.__sync_request_handler: BaseRequestHandler[_RequestT, _ResponseT] = sync_request_handler
        self.__thread_pool_size: int | None = thread_pool_size
        self.__request_thread_pool: AbstractAsyncThreadPoolExecutor | None = None

    @abstractmethod
    def _build_client_wrapper(self, client: AsyncClientInterface[_ResponseT]) -> ClientInterface[_ResponseT]:
        raise NotImplementedError

    async def service_init(self, backend: AbstractAsyncBackend) -> None:
        await super().service_init(backend)
        self.__backend = backend
        await backend.run_in_thread(self.sync_request_handler.service_init)
        self.__request_thread_pool = backend.create_thread_pool_executor(max_workers=self.__thread_pool_size)

    async def service_quit(self) -> None:
        try:
            async with contextlib.AsyncExitStack() as stack:
                thread_pool = self.__request_thread_pool
                backend = self.__backend
                if backend is not None:
                    stack.push_async_callback(backend.run_in_thread, self.sync_request_handler.service_quit)  # type: ignore[arg-type]
                if thread_pool is not None:
                    stack.push_async_callback(thread_pool.shutdown)
        finally:
            self.__request_thread_pool = None
            self.__backend = None
            await super().service_quit()

    async def service_actions(self) -> None:
        await super().service_actions()
        await self.backend.run_in_thread(self.sync_request_handler.service_actions)

    async def handle(self, request: _RequestT, client: AsyncClientInterface[_ResponseT]) -> None:
        assert self.__request_thread_pool is not None, "service_init() was not called"
        sync_client = self._build_client_wrapper(client)
        return await self.__request_thread_pool.run(self.sync_request_handler.handle, request, sync_client)

    async def bad_request(self, client: AsyncClientInterface[_ResponseT], exc: BaseProtocolParseError) -> None:
        try:
            assert self.__request_thread_pool is not None, "service_init() was not called"
            sync_client = self._build_client_wrapper(client)
            return await self.__request_thread_pool.run(self.sync_request_handler.bad_request, sync_client, exc)
        finally:
            del exc

    async def handle_error(self, client: AsyncClientInterface[_ResponseT], exc: Exception) -> bool:
        try:
            sync_client = self._build_client_wrapper(client)
            return await self.backend.run_in_thread(self.sync_request_handler.handle_error, sync_client, exc)
        finally:
            del exc

    @property
    def backend(self) -> AbstractAsyncBackend:
        backend = self.__backend
        assert backend is not None, "service_init() was not called"
        return backend

    @property
    def sync_request_handler(self) -> BaseRequestHandler[_RequestT, _ResponseT]:
        return self.__sync_request_handler


@final
class StreamRequestHandlerAsyncBridge(
    _BaseAsyncWrapperForRequestHandler[_RequestT, _ResponseT],
    AsyncStreamRequestHandler[_RequestT, _ResponseT],
):
    __slots__ = ("__clients",)

    def __init__(
        self,
        sync_request_handler: BaseRequestHandler[_RequestT, _ResponseT],
        thread_pool_size: int | None = None,
    ) -> None:
        super().__init__(sync_request_handler, thread_pool_size=thread_pool_size)

        self.__clients: WeakKeyDictionary[AsyncClientInterface[_ResponseT], ClientInterface[_ResponseT]] | None = None

    def _build_client_wrapper(self, client: AsyncClientInterface[_ResponseT]) -> ClientInterface[_ResponseT]:
        assert self.__clients is not None, "service_init() was not called"
        assert client in self.__clients, f"on_connection() was not called for {client}"
        return self.__clients[client]

    async def service_init(self, backend: AbstractAsyncBackend) -> None:
        await super().service_init(backend)
        self.__clients = WeakKeyDictionary()

    async def service_quit(self) -> None:
        try:
            clients, self.__clients = self.__clients, None
            if clients is not None:
                clients.clear()
        finally:
            await super().service_quit()

    async def on_connection(self, client: AsyncClientInterface[_ResponseT]) -> None:
        assert self.__clients is not None, "service_init() was not called"
        assert isinstance(client, AsyncClientInterface)
        await super().on_connection(client)
        try:
            sync_client = self.__clients[client]
        except KeyError:
            sync_client = _BlockingClientInterfaceWrapper(self.backend.create_threads_portal(), client)
            self.__clients[client] = sync_client
        if isinstance(self.sync_request_handler, StreamRequestHandler):
            await self.backend.run_in_thread(self.sync_request_handler.on_connection, sync_client)

    async def on_disconnection(self, client: AsyncClientInterface[_ResponseT]) -> None:
        assert self.__clients is not None, "service_init() was not called"
        try:
            assert client in self.__clients, f"on_disconnection() called before on_connection() for {client}"
            # Do not remove the client from the dictionary, because other operations such as handle_error() will need it.
            # Since it is a WeakKeyDictionary, the client will be removed on garbage collection
            sync_client = self.__clients[client]
            if isinstance(self.sync_request_handler, StreamRequestHandler):
                await self.backend.run_in_thread(self.sync_request_handler.on_disconnection, sync_client)
        finally:
            await super().on_disconnection(client)


@final
class DatagramRequestHandlerAsyncBridge(
    _BaseAsyncWrapperForRequestHandler[_RequestT, _ResponseT],
    AsyncDatagramRequestHandler[_RequestT, _ResponseT],
):
    __slots__ = ()

    def _build_client_wrapper(self, client: AsyncClientInterface[_ResponseT]) -> ClientInterface[_ResponseT]:
        return _BlockingClientInterfaceWrapper(self.backend.create_threads_portal(), client)

    async def accept_request_from(self, client_address: SocketAddress) -> bool:
        if isinstance(self.sync_request_handler, DatagramRequestHandler):
            return await self.backend.run_in_thread(self.sync_request_handler.accept_request_from, client_address)
        return await super().accept_request_from(client_address)


@final
class _BlockingClientInterfaceWrapper(ClientInterface[_ResponseT]):
    __slots__ = ("__threads_portal", "__async_client", "__socket_proxy", "__h")

    def __init__(self, threads_portal: AbstractThreadsPortal, async_client: AsyncClientInterface[_ResponseT]) -> None:
        super().__init__(async_client.address)

        self.__threads_portal: AbstractThreadsPortal = threads_portal
        self.__async_client: AsyncClientInterface[_ResponseT] = async_client
        self.__socket_proxy: SocketProxy = SocketProxy(async_client.socket, runner=threads_portal.run_sync)
        self.__h: int | None = None

    def __hash__(self) -> int:
        if (h := self.__h) is None:
            self.__h = h = hash((_BlockingClientInterfaceWrapper, self.__async_client, 0xFF))
        return h

    def __eq__(self, other: object, /) -> bool:
        if not isinstance(other, _BlockingClientInterfaceWrapper):
            return NotImplemented
        return self.__async_client == other.__async_client

    def is_closed(self) -> bool:
        return self.__threads_portal.run_sync(self.__async_client.is_closing)

    def close(self) -> None:
        return self.__threads_portal.run_coroutine(self.__async_client.aclose)

    def send_packet(self, packet: _ResponseT) -> None:
        return self.__threads_portal.run_coroutine(self.__async_client.send_packet, packet)

    @property
    def socket(self) -> SocketProxy:
        return self.__socket_proxy
