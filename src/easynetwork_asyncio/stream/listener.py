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
from abc import abstractmethod
from typing import TYPE_CHECKING, Any, Callable, final

from easynetwork.api_async.backend.abc import (
    AbstractAcceptedSocket,
    AbstractAsyncListenerSocketAdapter,
    AbstractAsyncStreamSocketAdapter,
)

if TYPE_CHECKING:
    import asyncio.trsock
    import socket as _socket


@final
class ListenerSocketAdapter(AbstractAsyncListenerSocketAdapter):
    __slots__ = ("__socket", "__accepted_socket_factory")

    def __init__(
        self,
        socket: _socket.socket,
        loop: asyncio.AbstractEventLoop,
        accepted_socket_factory: Callable[[_socket.socket, asyncio.AbstractEventLoop], AbstractAcceptedSocket],
    ) -> None:
        super().__init__()

        from ..socket import AsyncSocket

        self.__socket: AsyncSocket = AsyncSocket(socket, loop)
        self.__accepted_socket_factory = accepted_socket_factory

    def is_closing(self) -> bool:
        return self.__socket.is_closing()

    async def aclose(self) -> None:
        return await self.__socket.aclose()

    async def abort(self) -> None:
        return await self.__socket.abort()

    async def accept(self) -> AbstractAcceptedSocket:
        client_socket, _ = await self.__socket.accept()
        return self.__accepted_socket_factory(client_socket, self.__socket.loop)

    def get_local_address(self) -> tuple[Any, ...]:
        return self.__socket.socket.getsockname()

    def socket(self) -> asyncio.trsock.TransportSocket:
        return self.__socket.socket


class _BaseAcceptedSocket(AbstractAcceptedSocket):
    __slots__ = (
        "__socket",
        "__loop",
    )

    def __init__(self, socket: _socket.socket, loop: asyncio.AbstractEventLoop) -> None:
        super().__init__()

        self.__socket: _socket.socket | None = socket
        self.__loop: asyncio.AbstractEventLoop = loop

    def __del__(self) -> None:  # pragma: no cover
        try:
            socket: _socket.socket | None = self.__socket
        except AttributeError:
            return
        if socket is not None:
            socket.close()

    async def connect(self) -> AbstractAsyncStreamSocketAdapter:
        socket, self.__socket = self.__socket, None
        assert socket is not None, f"{self.__class__.__name__}.connect() called twice"

        return await self._make_socket_adapter(socket)

    @abstractmethod
    async def _make_socket_adapter(self, socket: _socket.socket) -> AbstractAsyncStreamSocketAdapter:
        raise NotImplementedError

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        return self.__loop


@final
class AcceptedSocket(_BaseAcceptedSocket):
    __slots__ = ("__use_asyncio_transport",)

    def __init__(self, socket: _socket.socket, loop: asyncio.AbstractEventLoop, *, use_asyncio_transport: bool = False) -> None:
        super().__init__(socket, loop)

        self.__use_asyncio_transport: bool = bool(use_asyncio_transport)

    async def _make_socket_adapter(self, socket: _socket.socket) -> AbstractAsyncStreamSocketAdapter:
        loop = self.loop
        if not self.__use_asyncio_transport:
            from .socket import RawStreamSocketAdapter

            return RawStreamSocketAdapter(socket, loop)

        from easynetwork.tools.socket import MAX_STREAM_BUFSIZE

        from .socket import AsyncioTransportStreamSocketAdapter

        reader = asyncio.streams.StreamReader(MAX_STREAM_BUFSIZE, loop)
        protocol = asyncio.streams.StreamReaderProtocol(reader, loop=loop)
        transport, protocol = await loop.connect_accepted_socket(lambda: protocol, socket)
        writer = asyncio.streams.StreamWriter(transport, protocol, reader, loop)
        return AsyncioTransportStreamSocketAdapter(reader, writer)
