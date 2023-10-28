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

__all__ = ["AsyncioTransportDatagramListenerSocketAdapter", "RawDatagramListenerSocketAdapter"]

import asyncio
import asyncio.streams
import socket as _socket
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, final

from easynetwork.lowlevel.api_async.transports import abc as transports
from easynetwork.lowlevel.constants import MAX_DATAGRAM_BUFSIZE
from easynetwork.lowlevel.socket import _get_socket_extra

from ..socket import AsyncSocket

if TYPE_CHECKING:
    import asyncio.trsock

    from .endpoint import DatagramEndpoint


@final
class AsyncioTransportDatagramListenerSocketAdapter(transports.AsyncDatagramListener[tuple[Any, ...]]):
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

    def is_closing(self) -> bool:
        return self.__closing

    async def aclose(self) -> None:
        self.__closing = True
        self.__endpoint.close()
        try:
            await self.__endpoint.wait_closed()
        except asyncio.CancelledError:
            self.__endpoint.transport.abort()
            raise

    async def recv_from(self) -> tuple[bytes, tuple[Any, ...]]:
        return await self.__endpoint.recvfrom()

    async def send_to(self, data: bytes | bytearray | memoryview, address: tuple[Any, ...]) -> None:
        await self.__endpoint.sendto(data, address)

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        socket = self.__socket
        return _get_socket_extra(socket, wrap_in_proxy=False)


@final
class RawDatagramListenerSocketAdapter(transports.AsyncDatagramListener[tuple[Any, ...]]):
    __slots__ = ("__socket",)

    def __init__(self, socket: _socket.socket, loop: asyncio.AbstractEventLoop) -> None:
        super().__init__()

        if socket.type != _socket.SOCK_DGRAM:
            raise ValueError("A 'SOCK_DGRAM' socket is expected")

        self.__socket: AsyncSocket = AsyncSocket(socket, loop)

    def is_closing(self) -> bool:
        return self.__socket.is_closing()

    async def aclose(self) -> None:
        return await self.__socket.aclose()

    async def recv_from(self) -> tuple[bytes, tuple[Any, ...]]:
        return await self.__socket.recvfrom(MAX_DATAGRAM_BUFSIZE)

    async def send_to(self, data: bytes | bytearray | memoryview, address: tuple[Any, ...]) -> None:
        await self.__socket.sendto(data, address)

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        socket = self.__socket.socket
        return _get_socket_extra(socket, wrap_in_proxy=False)
