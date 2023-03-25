# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""asyncio engine for easynetwork.async
"""

from __future__ import annotations

__all__ = [
    "StreamSocketAdapter",
]

import socket as _socket
from typing import TYPE_CHECKING, Any, final

from easynetwork.async_api.backend.abc import AbstractStreamSocketAdapter
from easynetwork.tools._utils import error_from_errno as _error_from_errno
from easynetwork.tools.socket import SocketProxy

if TYPE_CHECKING:
    import asyncio

    from _typeshed import ReadableBuffer

    from . import AsyncioBackend


@final
class StreamSocketAdapter(AbstractStreamSocketAdapter):
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

        socket: _socket.socket | None = writer.get_extra_info("socket")
        assert isinstance(socket, _socket.socket), "Writer transport must be a socket transport"
        if writer.get_extra_info("peername") is None:
            import errno

            raise _error_from_errno(errno.ENOTCONN)

        self.__proxy: SocketProxy = SocketProxy(socket)

    def __del__(self) -> None:  # pragma: no cover
        try:
            writer = self.__writer
        except AttributeError:
            return
        writer.close()

    async def close(self) -> None:
        self.__writer.close()
        await self.__writer.wait_closed()

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
