# -*- coding: utf-8 -*-
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
from easynetwork.tools.socket import MAX_STREAM_BUFSIZE

from ..socket import AsyncSocket
from .socket import AsyncioTransportStreamSocketAdapter, RawStreamSocketAdapter

if TYPE_CHECKING:
    import asyncio.trsock
    import socket as _socket
    import ssl as _ssl


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

        self.__socket: AsyncSocket = AsyncSocket(socket, loop)
        self.__accepted_socket_factory = accepted_socket_factory

    def is_closing(self) -> bool:
        return self.__socket.is_closing()

    async def aclose(self) -> None:
        return await self.__socket.aclose()

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
            return RawStreamSocketAdapter(socket, loop)

        reader = asyncio.streams.StreamReader(MAX_STREAM_BUFSIZE, loop)
        protocol = asyncio.streams.StreamReaderProtocol(reader, loop=loop)
        transport, _ = await loop.connect_accepted_socket(lambda: protocol, socket)
        writer = asyncio.streams.StreamWriter(transport, protocol, reader, loop)
        return AsyncioTransportStreamSocketAdapter(reader, writer)


@final
class AcceptedSSLSocket(_BaseAcceptedSocket):
    __slots__ = ("__ssl_context", "__ssl_handshake_timeout", "__ssl_shutdown_timeout")

    def __init__(
        self,
        socket: _socket.socket,
        loop: asyncio.AbstractEventLoop,
        ssl_context: _ssl.SSLContext,
        *,
        ssl_handshake_timeout: float,
        ssl_shutdown_timeout: float,
    ) -> None:
        super().__init__(socket, loop)

        assert ssl_context is not None

        self.__ssl_context: _ssl.SSLContext = ssl_context
        self.__ssl_handshake_timeout: float = float(ssl_handshake_timeout)
        self.__ssl_shutdown_timeout: float = float(ssl_shutdown_timeout)

    async def _make_socket_adapter(self, socket: _socket.socket) -> AbstractAsyncStreamSocketAdapter:
        loop = self.loop
        reader = asyncio.streams.StreamReader(MAX_STREAM_BUFSIZE, loop)
        protocol = asyncio.streams.StreamReaderProtocol(reader, loop=loop)
        transport, _ = await loop.connect_accepted_socket(
            lambda: protocol,
            socket,
            ssl=self.__ssl_context,
            ssl_handshake_timeout=self.__ssl_handshake_timeout,
            ssl_shutdown_timeout=self.__ssl_shutdown_timeout,
        )
        writer = asyncio.streams.StreamWriter(transport, protocol, reader, loop)
        return AsyncioTransportStreamSocketAdapter(reader, writer)
