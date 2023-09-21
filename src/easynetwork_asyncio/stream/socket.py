# Copyright 2021-2023, Francis Clairicia-Rose-Claire-Josephine
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
#
"""asyncio engine for easynetwork.async
"""

from __future__ import annotations

__all__ = ["AsyncioTransportStreamSocketAdapter", "RawStreamSocketAdapter"]

import asyncio
import socket as _socket
from collections.abc import Iterable
from typing import TYPE_CHECKING, final

from easynetwork.api_async.backend.abc import AsyncStreamSocketAdapter as AbstractAsyncStreamSocketAdapter

from ..socket import AsyncSocket

if TYPE_CHECKING:
    import asyncio.trsock


@final
class AsyncioTransportStreamSocketAdapter(AbstractAsyncStreamSocketAdapter):
    __slots__ = (
        "__reader",
        "__writer",
        "__socket",
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

    async def send_eof(self) -> None:
        self.__writer.write_eof()
        await asyncio.sleep(0)

    def socket(self) -> asyncio.trsock.TransportSocket:
        return self.__socket


@final
class RawStreamSocketAdapter(AbstractAsyncStreamSocketAdapter):
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
