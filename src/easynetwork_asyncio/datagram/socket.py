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

__all__ = ["AsyncioTransportDatagramSocketAdapter", "RawDatagramSocketAdapter"]

import asyncio
import errno
import socket as _socket
from typing import TYPE_CHECKING, Any, final

from easynetwork.api_async.backend.abc import AbstractAsyncDatagramSocketAdapter
from easynetwork.tools._utils import error_from_errno as _error_from_errno

from ..socket import AsyncSocket

if TYPE_CHECKING:
    import asyncio.trsock

    from .endpoint import DatagramEndpoint


@final
class AsyncioTransportDatagramSocketAdapter(AbstractAsyncDatagramSocketAdapter):
    __slots__ = (
        "__endpoint",
        "__socket",
    )

    def __init__(self, endpoint: DatagramEndpoint) -> None:
        super().__init__()
        self.__endpoint: DatagramEndpoint = endpoint

        socket: asyncio.trsock.TransportSocket | None = endpoint.get_extra_info("socket")
        assert socket is not None, "transport must be a socket transport"  # nosec assert_used

        self.__socket: asyncio.trsock.TransportSocket = socket

    async def aclose(self) -> None:
        try:
            self.__endpoint.close()
            return await self.__endpoint.wait_closed()
        except asyncio.CancelledError:
            self.__endpoint.transport.abort()
            raise

    def is_closing(self) -> bool:
        return self.__endpoint.is_closing()

    def get_local_address(self) -> tuple[Any, ...]:
        local_address: tuple[Any, ...] | None = self.__endpoint.get_extra_info("sockname")
        if local_address is None:
            raise _error_from_errno(errno.ENOTSOCK)
        return local_address

    def get_remote_address(self) -> tuple[Any, ...] | None:
        return self.__endpoint.get_extra_info("peername")

    async def recvfrom(self, bufsize: int, /) -> tuple[bytes, tuple[Any, ...]]:
        data, address = await self.__endpoint.recvfrom()
        if len(data) > bufsize:
            data = data[:bufsize]
        return data, address

    async def sendto(self, data: bytes, address: tuple[Any, ...] | None, /) -> None:
        await self.__endpoint.sendto(data, address)

    def socket(self) -> asyncio.trsock.TransportSocket:
        return self.__socket


@final
class RawDatagramSocketAdapter(AbstractAsyncDatagramSocketAdapter):
    __slots__ = ("__socket",)

    def __init__(
        self,
        socket: _socket.socket,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        super().__init__()

        if socket.type != _socket.SOCK_DGRAM:
            raise ValueError("A 'SOCK_DGRAM' socket is expected")

        self.__socket: AsyncSocket = AsyncSocket(socket, loop)

    async def aclose(self) -> None:
        return await self.__socket.aclose()

    def is_closing(self) -> bool:
        return self.__socket.is_closing()

    def get_local_address(self) -> tuple[Any, ...]:
        return self.__socket.socket.getsockname()

    def get_remote_address(self) -> tuple[Any, ...] | None:
        try:
            return self.__socket.socket.getpeername()
        except OSError:
            return None

    async def recvfrom(self, bufsize: int, /) -> tuple[bytes, tuple[Any, ...]]:
        return await self.__socket.recvfrom(bufsize)

    async def sendto(self, data: bytes, address: tuple[Any, ...] | None, /) -> None:
        if address is None:
            await self.__socket.sendall(data)
        else:
            await self.__socket.sendto(data, address)

    def socket(self) -> asyncio.trsock.TransportSocket:
        return self.__socket.socket
