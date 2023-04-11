# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""sync-to-async bridge for request handlers"""

from __future__ import annotations

__all__ = [
    "AsyncDatagramRequestHandlerBridge",
    "AsyncStreamRequestHandlerBridge",
]

from abc import abstractmethod
from typing import TYPE_CHECKING, TypeVar, final

from ...api_sync.server.handler import BaseRequestHandler, ClientInterface, DatagramRequestHandler, StreamRequestHandler
from .handler import AsyncBaseRequestHandler, AsyncClientInterface, AsyncDatagramRequestHandler, AsyncStreamRequestHandler

if TYPE_CHECKING:
    from ...exceptions import BaseProtocolParseError
    from ...tools.socket import SocketAddress, SocketProxy
    from ..backend.abc import AbstractAsyncBackend


_RequestT = TypeVar("_RequestT")
_ResponseT = TypeVar("_ResponseT")


class _BaseAsyncWrapperForRequestHandler(AsyncBaseRequestHandler[_RequestT, _ResponseT]):
    __slots__ = (
        "__backend",
        "__sync_request_handler",
    )

    def __init__(self, backend: AbstractAsyncBackend, sync_request_handler: BaseRequestHandler[_RequestT, _ResponseT]) -> None:
        super().__init__()

        self.__backend: AbstractAsyncBackend = backend
        self.__sync_request_handler: BaseRequestHandler[_RequestT, _ResponseT] = sync_request_handler

    @abstractmethod
    def _build_client_wrapper(self, client: AsyncClientInterface[_ResponseT]) -> ClientInterface[_ResponseT]:
        raise NotImplementedError

    async def service_init(self) -> None:
        await super().service_init()
        await self.backend.run_in_thread(self.sync_request_handler.service_init)

    async def service_quit(self) -> None:
        try:
            await self.backend.run_in_thread(self.sync_request_handler.service_quit)
        finally:
            await super().service_quit()

    async def service_actions(self) -> None:
        await super().service_actions()
        await self.backend.run_in_thread(self.sync_request_handler.service_actions)

    async def handle(self, request: _RequestT, client: AsyncClientInterface[_ResponseT]) -> None:
        sync_client = self._build_client_wrapper(client)
        return await self.backend.run_in_thread(self.sync_request_handler.handle, request, sync_client)

    async def bad_request(self, client: AsyncClientInterface[_ResponseT], exc: BaseProtocolParseError) -> None:
        sync_client = self._build_client_wrapper(client)
        try:
            return await self.backend.run_in_thread(self.sync_request_handler.bad_request, sync_client, exc)
        finally:
            del exc

    async def handle_error(self, client: AsyncClientInterface[_ResponseT], exc: Exception) -> bool:
        sync_client = self._build_client_wrapper(client)
        try:
            return await self.backend.run_in_thread(self.sync_request_handler.handle_error, sync_client, exc)
        finally:
            del exc

    @property
    def backend(self) -> AbstractAsyncBackend:
        return self.__backend

    @property
    def sync_request_handler(self) -> BaseRequestHandler[_RequestT, _ResponseT]:
        return self.__sync_request_handler


@final
class AsyncStreamRequestHandlerBridge(
    _BaseAsyncWrapperForRequestHandler[_RequestT, _ResponseT],
    AsyncStreamRequestHandler[_RequestT, _ResponseT],
):
    __slots__ = ("__clients",)

    def __init__(self, backend: AbstractAsyncBackend, sync_request_handler: BaseRequestHandler[_RequestT, _ResponseT]) -> None:
        super().__init__(backend, sync_request_handler)

        from weakref import WeakKeyDictionary

        self.__clients: WeakKeyDictionary[AsyncClientInterface[_ResponseT], ClientInterface[_ResponseT]] = WeakKeyDictionary()

    def _build_client_wrapper(self, client: AsyncClientInterface[_ResponseT]) -> ClientInterface[_ResponseT]:
        return self.__clients[client]

    async def on_connection(self, client: AsyncClientInterface[_ResponseT]) -> None:
        assert isinstance(client, AsyncClientInterface)
        assert client not in self.__clients
        await super().on_connection(client)
        sync_client = _BlockingClientInterfaceWrapper(self.backend, client)
        self.__clients[client] = sync_client
        if isinstance(self.sync_request_handler, StreamRequestHandler):
            await self.backend.run_in_thread(self.sync_request_handler.on_connection, sync_client)

    async def on_disconnection(self, client: AsyncClientInterface[_ResponseT]) -> None:
        try:
            # Do not remove the client from the dictionary, because other operations such as handle_error() will need it.
            # Since it is a WeakKeyDictionary, the client will be removed on garbage collection
            sync_client = self.__clients[client]
            if isinstance(self.sync_request_handler, StreamRequestHandler):
                await self.backend.run_in_thread(self.sync_request_handler.on_disconnection, sync_client)
        finally:
            await super().on_disconnection(client)


@final
class AsyncDatagramRequestHandlerBridge(
    _BaseAsyncWrapperForRequestHandler[_RequestT, _ResponseT],
    AsyncDatagramRequestHandler[_RequestT, _ResponseT],
):
    __slots__ = ()

    def _build_client_wrapper(self, client: AsyncClientInterface[_ResponseT]) -> ClientInterface[_ResponseT]:
        return _BlockingClientInterfaceWrapper(self.backend, client)

    async def accept_request_from(self, client_address: SocketAddress) -> bool:
        if isinstance(self.sync_request_handler, DatagramRequestHandler):
            return await self.backend.run_in_thread(self.sync_request_handler.accept_request_from, client_address)
        return await super().accept_request_from(client_address)


@final
class _BlockingClientInterfaceWrapper(ClientInterface[_ResponseT]):
    __slots__ = ("__backend", "__async_client", "__h")

    def __init__(self, backend: AbstractAsyncBackend, async_client: AsyncClientInterface[_ResponseT]) -> None:
        super().__init__(async_client.address)

        from weakref import proxy

        self.__backend: AbstractAsyncBackend = backend
        self.__async_client: AsyncClientInterface[_ResponseT] = proxy(async_client)
        self.__h: int = hash(async_client)

    def __hash__(self) -> int:
        return self.__h

    def __eq__(self, other: object, /) -> bool:
        if not isinstance(other, _BlockingClientInterfaceWrapper):
            return NotImplemented
        return self.__async_client == other.__async_client

    def is_closed(self) -> bool:
        return self.__backend.run_sync_threadsafe(self.__async_client.is_closing)

    def close(self) -> None:
        return self.__backend.run_coroutine_from_thread(self.__async_client.close)

    def send_packet(self, packet: _ResponseT) -> None:
        return self.__backend.run_coroutine_from_thread(self.__async_client.send_packet, packet)

    @property
    def socket(self) -> SocketProxy:
        return self.__async_client.socket