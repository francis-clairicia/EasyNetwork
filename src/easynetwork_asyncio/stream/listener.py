# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""asyncio engine for easynetwork.async
"""

from __future__ import annotations

__all__ = ["ListenerSocketAdapter"]

import asyncio
import asyncio.streams
from typing import TYPE_CHECKING, Any, final

from easynetwork.api_async.backend.abc import AbstractAsyncListenerSocketAdapter, AbstractAsyncStreamSocketAdapter

if TYPE_CHECKING:
    import asyncio.trsock
    import socket as _socket


@final
class ListenerSocketAdapter(AbstractAsyncListenerSocketAdapter):
    __slots__ = ("__socket",)

    def __init__(self, socket: _socket.socket, loop: asyncio.AbstractEventLoop) -> None:
        super().__init__()

        from ..socket import AsyncSocket

        self.__socket: AsyncSocket = AsyncSocket(socket, loop)

    def is_closing(self) -> bool:
        return self.__socket.is_closing()

    async def aclose(self) -> None:
        return await self.__socket.aclose()

    async def abort(self) -> None:
        return await self.__socket.abort()

    async def accept(self) -> AbstractAsyncStreamSocketAdapter:
        client_socket, client_address = await self.__socket.accept()
        client_socket_adapter = await self._make_socket_adapter(client_socket, client_address)
        assert client_socket_adapter.get_remote_address() == client_address
        return client_socket_adapter

    async def _make_socket_adapter(self, socket: _socket.socket, address: tuple[Any, ...]) -> AbstractAsyncStreamSocketAdapter:
        from easynetwork.tools.socket import MAX_STREAM_BUFSIZE

        from .socket import TransportBasedStreamSocketAdapter

        loop = self.__socket.loop
        reader = asyncio.streams.StreamReader(MAX_STREAM_BUFSIZE, loop)
        protocol = asyncio.streams.StreamReaderProtocol(reader, loop=loop)
        transport, protocol = await loop.connect_accepted_socket(lambda: protocol, socket)
        writer = asyncio.streams.StreamWriter(transport, protocol, reader, loop)
        return TransportBasedStreamSocketAdapter(reader, writer, remote_address=address)

    def get_local_address(self) -> tuple[Any, ...]:
        return self.__socket.socket.getsockname()

    def socket(self) -> asyncio.trsock.TransportSocket:
        return self.__socket.socket
