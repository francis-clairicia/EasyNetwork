# -*- coding: utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""asyncio engine for easynetwork.async
"""

from __future__ import annotations

__all__ = ["AsyncioTransportStreamSocketAdapter", "RawStreamSocketAdapter"]

import asyncio
import errno
import socket as _socket
from typing import TYPE_CHECKING, Any, final

from easynetwork.api_async.backend.abc import AbstractAsyncStreamSocketAdapter
from easynetwork.tools._utils import error_from_errno as _error_from_errno

from ..socket import AsyncSocket

if TYPE_CHECKING:
    import asyncio.trsock

    from _typeshed import ReadableBuffer


@final
class AsyncioTransportStreamSocketAdapter(AbstractAsyncStreamSocketAdapter):
    __slots__ = (
        "__reader",
        "__writer",
        "__remote_addr",
    )

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        super().__init__()
        self.__reader: asyncio.StreamReader = reader
        self.__writer: asyncio.StreamWriter = writer

        socket: asyncio.trsock.TransportSocket | None = writer.get_extra_info("socket")
        assert socket is not None, "Writer transport must be a socket transport"
        remote_address = writer.get_extra_info("peername")
        if remote_address is None:
            raise _error_from_errno(errno.ENOTCONN)
        self.__remote_addr: tuple[Any, ...] = tuple(remote_address)

    async def aclose(self) -> None:
        try:
            if not self.__writer.is_closing():
                self.__writer.close()
            await self.__writer.wait_closed()
        except (ConnectionError, TimeoutError):
            # It is normal if there was connection errors during operations. But do not propagate this exception,
            # as we will never reuse this socket
            pass
        except asyncio.CancelledError:
            try:
                self.__writer.transport.abort()
            finally:
                raise

    def is_closing(self) -> bool:
        return self.__writer.is_closing()

    def get_local_address(self) -> tuple[Any, ...]:
        return self.__writer.get_extra_info("sockname")

    def get_remote_address(self) -> tuple[Any, ...]:
        return self.__remote_addr

    async def recv(self, bufsize: int, /) -> bytes:
        if bufsize < 0:
            raise ValueError("'bufsize' must be a positive or null integer")
        if bufsize == 0:
            return b""
        return await self.__reader.read(bufsize)

    async def sendall(self, data: ReadableBuffer, /) -> None:
        self.__writer.write(memoryview(data).toreadonly())
        await self.__writer.drain()

    def socket(self) -> asyncio.trsock.TransportSocket:
        socket: asyncio.trsock.TransportSocket = self.__writer.get_extra_info("socket")
        return socket


@final
class RawStreamSocketAdapter(AbstractAsyncStreamSocketAdapter):
    __slots__ = (
        "__socket",
        "__remote_addr",
    )

    def __init__(
        self,
        socket: _socket.socket,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        super().__init__()

        self.__socket: AsyncSocket = AsyncSocket(socket, loop)

        assert socket.type == _socket.SOCK_STREAM, "A 'SOCK_STREAM' socket is expected"

        remote_address = socket.getpeername()
        self.__remote_addr: tuple[Any, ...] = tuple(remote_address)

    async def aclose(self) -> None:
        return await self.__socket.aclose()

    def is_closing(self) -> bool:
        return self.__socket.is_closing()

    def get_local_address(self) -> tuple[Any, ...]:
        return self.__socket.socket.getsockname()

    def get_remote_address(self) -> tuple[Any, ...]:
        return self.__remote_addr

    async def recv(self, bufsize: int, /) -> bytes:
        return await self.__socket.recv(bufsize)

    async def sendall(self, data: ReadableBuffer, /) -> None:
        await self.__socket.sendall(data)

    def socket(self) -> asyncio.trsock.TransportSocket:
        return self.__socket.socket
