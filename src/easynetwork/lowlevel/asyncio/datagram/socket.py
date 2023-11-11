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
import socket as _socket
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, final

from ... import constants, socket as socket_tools
from ...api_async.transports import abc as transports
from ..socket import AsyncSocket

if TYPE_CHECKING:
    import asyncio.trsock

    from .endpoint import DatagramEndpoint


@final
class AsyncioTransportDatagramSocketAdapter(transports.AsyncDatagramTransport):
    __slots__ = (
        "__endpoint",
        "__socket",
        "__closing",
    )

    def __init__(self, endpoint: DatagramEndpoint) -> None:
        super().__init__()
        self.__endpoint: DatagramEndpoint = endpoint

        socket: asyncio.trsock.TransportSocket | None = endpoint.get_extra_info("socket")
        assert socket is not None, "transport must be a socket transport"  # nosec assert_used

        self.__socket: asyncio.trsock.TransportSocket = socket
        # asyncio.DatagramTransport.is_closing() can suddently become true if there is something wrong with the socket
        # even if transport.close() was never called.
        # To bypass this side effect, we use our own flag.
        self.__closing: bool = False

    async def aclose(self) -> None:
        self.__closing = True
        await self.__endpoint.aclose()

    def is_closing(self) -> bool:
        return self.__closing

    async def recv(self) -> bytes:
        data, _ = await self.__endpoint.recvfrom()
        return data

    async def send(self, data: bytes | bytearray | memoryview) -> None:
        await self.__endpoint.sendto(data, None)

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        socket = self.__socket
        return socket_tools._get_socket_extra(socket, wrap_in_proxy=False)


@final
class RawDatagramSocketAdapter(transports.AsyncDatagramTransport):
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

    async def recv(self) -> bytes:
        data, _ = await self.__socket.recvfrom(constants.MAX_DATAGRAM_BUFSIZE)
        return data

    async def send(self, data: bytes | bytearray | memoryview) -> None:
        await self.__socket.sendall(data)

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        socket = self.__socket.socket
        return socket_tools._get_socket_extra(socket, wrap_in_proxy=False)
