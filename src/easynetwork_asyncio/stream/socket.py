# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""asyncio engine for easynetwork.async
"""

from __future__ import annotations

__all__ = ["StreamSocketAdapter"]

from typing import TYPE_CHECKING, Any, final

from easynetwork.api_async.backend.abc import AbstractAsyncListenerSocketAdapter, AbstractAsyncStreamSocketAdapter
from easynetwork.tools._utils import error_from_errno as _error_from_errno
from easynetwork.tools.socket import SocketProxy

if TYPE_CHECKING:
    import asyncio
    import asyncio.trsock
    import socket as _socket

    from _typeshed import ReadableBuffer

    from ..backend import AsyncioBackend


@final
class ListenerSocketAdapter(AbstractAsyncListenerSocketAdapter):
    __slots__ = (
        "__backend",
        "__socket",
        "__loop",
        "__proxy",
        "__accept_task",
        "__closed",
    )

    def __init__(self, backend: AsyncioBackend, socket: _socket.socket, *, loop: asyncio.AbstractEventLoop | None = None) -> None:
        super().__init__()
        if loop is None:
            import asyncio

            loop = asyncio.get_running_loop()

        self.__backend: AsyncioBackend = backend
        self.__socket: _socket.socket = socket
        self.__loop: asyncio.AbstractEventLoop = loop
        self.__proxy: SocketProxy = SocketProxy(socket)
        self.__accept_task: asyncio.Task[tuple[_socket.socket, tuple[Any, ...]]] | None = None
        self.__closed: bool = False

    def is_closing(self) -> bool:
        return self.__closed

    async def close(self) -> None:
        if self.__closed:
            return

        self.__closed = True
        if self.__accept_task is not None and not self.__accept_task.done():
            self.__accept_task.cancel()
            self.__accept_task = None

        self.__socket.close()

    async def abort(self) -> None:
        return await self.close()

    async def accept(self) -> tuple[AbstractAsyncStreamSocketAdapter, tuple[Any, ...]]:
        if self.__closed:
            import errno

            raise _error_from_errno(errno.EBADFD)
        if self.__accept_task is not None:
            raise RuntimeError("accept() is already awaited")

        self.__accept_task = self.__loop.create_task(self.__loop.sock_accept(self.__socket))
        try:
            client_socket, client_address = await self.__accept_task
        finally:
            self.__accept_task = None

        from asyncio.streams import StreamReader, StreamReaderProtocol, StreamWriter

        from easynetwork.tools.socket import MAX_STREAM_BUFSIZE

        client_reader = StreamReader(MAX_STREAM_BUFSIZE, self.__loop)
        client_transport, client_protocol = await self.__loop.connect_accepted_socket(
            lambda: StreamReaderProtocol(client_reader, loop=self.__loop), client_socket
        )
        client_writer = StreamWriter(client_transport, client_protocol, client_reader, self.__loop)
        return StreamSocketAdapter(self.__backend, client_reader, client_writer), client_address

    def getpeername(self) -> None:
        return None

    def getsockname(self) -> tuple[Any, ...]:
        return self.__socket.getsockname()

    def proxy(self) -> SocketProxy:
        return self.__proxy

    def get_backend(self) -> AsyncioBackend:
        return self.__backend


@final
class StreamSocketAdapter(AbstractAsyncStreamSocketAdapter):
    __slots__ = (
        "__backend",
        "__reader",
        "__writer",
        "__proxy",
    )

    def __init__(self, backend: AsyncioBackend, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        super().__init__()
        self.__backend: AsyncioBackend = backend
        self.__reader: asyncio.StreamReader = reader
        self.__writer: asyncio.StreamWriter = writer

        socket: asyncio.trsock.TransportSocket | None = writer.get_extra_info("socket")
        assert socket is not None, "Writer transport must be a socket transport"
        if writer.get_extra_info("peername") is None:
            import errno

            raise _error_from_errno(errno.ENOTCONN)

        self.__proxy: SocketProxy = SocketProxy(socket)

    async def close(self) -> None:
        self.__writer.close()
        await self.__writer.wait_closed()

    async def abort(self) -> None:
        self.__writer.transport.abort()

    def is_closing(self) -> bool:
        return self.__writer.is_closing()

    def getsockname(self) -> tuple[Any, ...]:
        return self.__writer.get_extra_info("sockname")

    def getpeername(self) -> tuple[Any, ...]:
        return self.__writer.get_extra_info("peername")

    async def recv(self, bufsize: int, /) -> bytes:
        if bufsize < 0:
            raise ValueError("'bufsize' must be a positive or null integer")
        if bufsize == 0:
            return b""
        return await self.__reader.read(bufsize)

    async def sendall(self, data: ReadableBuffer, /) -> None:
        with memoryview(data).toreadonly() as data_view:
            self.__writer.write(data_view)
            await self.__writer.drain()

    def proxy(self) -> SocketProxy:
        return self.__proxy

    def get_backend(self) -> AsyncioBackend:
        return self.__backend
