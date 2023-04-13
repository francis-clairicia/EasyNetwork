# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""asyncio engine for easynetwork.async
"""

from __future__ import annotations

__all__ = ["StreamSocketAdapter"]

from typing import TYPE_CHECKING, Any, final

from easynetwork.api_async.backend.abc import AbstractAsyncStreamSocketAdapter
from easynetwork.tools._utils import error_from_errno as _error_from_errno

if TYPE_CHECKING:
    import asyncio
    import asyncio.trsock

    from _typeshed import ReadableBuffer


@final
class StreamSocketAdapter(AbstractAsyncStreamSocketAdapter):
    __slots__ = (
        "__reader",
        "__writer",
    )

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        super().__init__()
        self.__reader: asyncio.StreamReader = reader
        self.__writer: asyncio.StreamWriter = writer

        socket: asyncio.trsock.TransportSocket | None = writer.get_extra_info("socket")
        assert socket is not None, "Writer transport must be a socket transport"
        if writer.get_extra_info("peername") is None:
            import errno

            raise _error_from_errno(errno.ENOTCONN)

    async def aclose(self) -> None:
        self.__writer.close()
        await self.__writer.wait_closed()

    async def abort(self) -> None:
        self.__writer.transport.abort()

    def is_closing(self) -> bool:
        return self.__writer.is_closing()

    def get_local_address(self) -> tuple[Any, ...]:
        return self.__writer.get_extra_info("sockname")

    def get_remote_address(self) -> tuple[Any, ...]:
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

    def socket(self) -> asyncio.trsock.TransportSocket:
        socket: asyncio.trsock.TransportSocket = self.__writer.get_extra_info("socket")
        return socket
