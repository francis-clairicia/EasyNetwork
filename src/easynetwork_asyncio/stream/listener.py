# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""asyncio engine for easynetwork.async
"""

from __future__ import annotations

__all__ = ["ListenerSocketAdapter"]

from typing import TYPE_CHECKING, Any, final

from easynetwork.api_async.backend.abc import AbstractAsyncListenerSocketAdapter, AbstractAsyncStreamSocketAdapter
from easynetwork.tools._utils import error_from_errno as _error_from_errno

if TYPE_CHECKING:
    import asyncio
    import asyncio.trsock
    import socket as _socket


@final
class ListenerSocketAdapter(AbstractAsyncListenerSocketAdapter):
    __slots__ = (
        "__socket",
        "__trsock",
        "__loop",
        "__accept_task",
    )

    def __init__(self, socket: _socket.socket, *, loop: asyncio.AbstractEventLoop | None = None) -> None:
        super().__init__()
        if loop is None:
            import asyncio

            loop = asyncio.get_running_loop()

        from asyncio.trsock import TransportSocket

        self.__socket: _socket.socket | None = socket
        self.__trsock: TransportSocket = TransportSocket(socket)
        self.__loop: asyncio.AbstractEventLoop = loop
        self.__accept_task: asyncio.Task[tuple[_socket.socket, _socket._RetAddress]] | None = None
        socket.setblocking(False)

    def __del__(self) -> None:  # pragma: no cover
        try:
            socket: _socket.socket | None = self.__socket
        except AttributeError:
            return
        if socket is not None:
            socket.close()

    def is_closing(self) -> bool:
        return self.__socket is None

    async def aclose(self) -> None:
        socket = self.__socket
        if socket is None:
            return

        self.__socket = None
        if self.__accept_task is not None and not self.__accept_task.done():
            self.__accept_task.cancel()
            self.__accept_task = None

        socket.close()

    async def abort(self) -> None:
        return await self.aclose()

    async def accept(self) -> AbstractAsyncStreamSocketAdapter:
        if self.__socket is None:
            import errno

            raise _error_from_errno(errno.EBADF)

        if self.__accept_task is not None:
            import errno

            raise _error_from_errno(errno.EBUSY)

        self.__accept_task = self.__loop.create_task(self.__loop.sock_accept(self.__socket))
        try:
            client_socket, client_address = await self.__accept_task
        finally:
            self.__accept_task = None

        client_socket_adapter = await self._make_socket_adapter(client_socket, client_address)
        assert client_socket_adapter.get_remote_address() == client_address
        return client_socket_adapter

    async def _make_socket_adapter(self, socket: _socket.socket, address: tuple[Any, ...]) -> AbstractAsyncStreamSocketAdapter:
        from asyncio.streams import StreamReader, StreamReaderProtocol, StreamWriter

        from easynetwork.tools.socket import MAX_STREAM_BUFSIZE

        from .socket import StreamSocketAdapter

        loop = self.__loop
        reader = StreamReader(MAX_STREAM_BUFSIZE, loop)
        protocol = StreamReaderProtocol(reader, loop=loop)
        transport, protocol = await loop.connect_accepted_socket(lambda: protocol, socket)
        writer = StreamWriter(transport, protocol, reader, loop)
        return StreamSocketAdapter(reader, writer, remote_address=address)

    def get_local_address(self) -> tuple[Any, ...]:
        return self.__trsock.getsockname()

    def socket(self) -> asyncio.trsock.TransportSocket:
        return self.__trsock
