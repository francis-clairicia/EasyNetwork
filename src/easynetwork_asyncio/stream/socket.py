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
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, Self, cast, final

from easynetwork.api_async.backend.abc import AbstractAsyncHalfCloseableStreamSocketAdapter, AbstractAsyncStreamSocketAdapter
from easynetwork.tools._utils import error_from_errno as _error_from_errno

from ..socket import AsyncSocket

if TYPE_CHECKING:
    import asyncio.trsock


class AsyncioTransportStreamSocketAdapter(AbstractAsyncStreamSocketAdapter):
    __slots__ = (
        "__reader",
        "__writer",
        "__socket",
    )

    def __new__(
        cls,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> Self:
        if cls is AsyncioTransportStreamSocketAdapter and writer.can_write_eof():
            return cast(Self, super().__new__(AsyncioTransportHalfCloseableStreamSocketAdapter))
        return super().__new__(cls)

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        super().__init__()
        self.__reader: asyncio.StreamReader = reader
        self.__writer: asyncio.StreamWriter = writer

        socket: asyncio.trsock.TransportSocket | None = writer.get_extra_info("socket")
        assert socket is not None, "Writer transport must be a socket transport"  # nosec assert_used
        self.__socket: asyncio.trsock.TransportSocket = socket

    async def aclose(self) -> None:
        try:
            if not self.__writer.is_closing():
                self.__writer.close()
            await self.__writer.wait_closed()
        except asyncio.CancelledError:
            self.__writer.transport.abort()
            raise

    def is_closing(self) -> bool:
        return self.__writer.is_closing()

    def get_local_address(self) -> tuple[Any, ...]:
        return self.__writer.get_extra_info("sockname")

    def get_remote_address(self) -> tuple[Any, ...]:
        remote_address: tuple[Any, ...] | None = self.__writer.get_extra_info("peername")
        if remote_address is None:
            raise _error_from_errno(errno.ENOTCONN)
        return remote_address

    async def recv(self, bufsize: int, /) -> bytes:
        if bufsize < 0:
            raise ValueError("'bufsize' must be a positive or null integer")
        return await self.__reader.read(bufsize)

    async def sendall(self, data: bytes, /) -> None:
        self.__writer.write(data)
        await self.__writer.drain()

    async def sendall_fromiter(self, iterable_of_data: Iterable[bytes], /) -> None:
        self.__writer.writelines(iterable_of_data)
        await self.__writer.drain()

    async def _send_eof_impl(self) -> None:
        assert self.__writer.can_write_eof()  # nosec assert_used
        self.__writer.write_eof()
        await asyncio.sleep(0)

    def socket(self) -> asyncio.trsock.TransportSocket:
        return self.__socket


@final
class AsyncioTransportHalfCloseableStreamSocketAdapter(
    AsyncioTransportStreamSocketAdapter,
    AbstractAsyncHalfCloseableStreamSocketAdapter,
):
    __slots__ = ()

    def __new__(cls, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> Self:
        if not writer.can_write_eof():
            raise ValueError(f"{writer!r} cannot write eof")
        return super().__new__(cls, reader, writer)

    send_eof = AsyncioTransportStreamSocketAdapter._send_eof_impl


@final
class RawStreamSocketAdapter(AbstractAsyncHalfCloseableStreamSocketAdapter):
    __slots__ = ("__socket",)

    def __init__(
        self,
        socket: _socket.socket,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        super().__init__()

        if socket.type != _socket.SOCK_STREAM:
            raise ValueError("A 'SOCK_STREAM' socket is expected")

        self.__socket: AsyncSocket = AsyncSocket(socket, loop)

    async def aclose(self) -> None:
        return await self.__socket.aclose()

    def is_closing(self) -> bool:
        return self.__socket.is_closing()

    def get_local_address(self) -> tuple[Any, ...]:
        return self.__socket.socket.getsockname()

    def get_remote_address(self) -> tuple[Any, ...]:
        return self.__socket.socket.getpeername()

    async def recv(self, bufsize: int, /) -> bytes:
        return await self.__socket.recv(bufsize)

    async def sendall(self, data: bytes, /) -> None:
        await self.__socket.sendall(data)

    async def send_eof(self) -> None:
        socket = self.__socket
        if socket.did_shutdown_SHUT_WR:
            # On macOS, calling shutdown a second time raises ENOTCONN, but
            # send_eof needs to be idempotent.
            await asyncio.sleep(0)
            return
        await socket.shutdown(_socket.SHUT_WR)

    def socket(self) -> asyncio.trsock.TransportSocket:
        return self.__socket.socket
