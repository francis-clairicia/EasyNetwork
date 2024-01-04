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

__all__ = ["DatagramListenerSocketAdapter"]

import asyncio
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, final

from ... import socket as socket_tools
from ...api_async.transports import abc as transports

if TYPE_CHECKING:
    import asyncio.trsock

    from .endpoint import DatagramEndpoint


@final
class DatagramListenerSocketAdapter(transports.AsyncDatagramListener[tuple[Any, ...]]):
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
        await self.__endpoint.aclose()

    async def recv_from(self) -> tuple[bytes, tuple[Any, ...]]:
        return await self.__endpoint.recvfrom()

    async def send_to(self, data: bytes | bytearray | memoryview, address: tuple[Any, ...]) -> None:
        await self.__endpoint.sendto(data, address)

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        socket = self.__socket
        return socket_tools._get_socket_extra(socket, wrap_in_proxy=False)
