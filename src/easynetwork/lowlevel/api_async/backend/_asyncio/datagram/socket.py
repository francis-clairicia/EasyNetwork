# Copyright 2021-2025, Francis Clairicia-Rose-Claire-Josephine
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
"""asyncio engine for easynetwork.async"""

from __future__ import annotations

__all__ = ["AsyncioTransportDatagramSocketAdapter"]

import asyncio
import asyncio.trsock
import warnings
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any, final

from ..... import _utils, socket as socket_tools
from ....transports.abc import AsyncDatagramTransport
from ...abc import AsyncBackend
from .endpoint import DatagramEndpoint


@final
class AsyncioTransportDatagramSocketAdapter(AsyncDatagramTransport):
    __slots__ = (
        "__backend",
        "__endpoint",
        "__closing",
        "__extra_attributes",
    )

    def __init__(self, backend: AsyncBackend, endpoint: DatagramEndpoint) -> None:
        super().__init__()

        socket: asyncio.trsock.TransportSocket | None = endpoint.get_extra_info("socket")
        if socket is None:
            raise AssertionError("transport must be a socket transport")

        self.__backend: AsyncBackend = backend
        self.__endpoint: DatagramEndpoint = endpoint

        # asyncio.DatagramTransport.is_closing() can suddently become true if there is something wrong with the socket
        # even if transport.close() was never called.
        # To bypass this side effect, we use our own flag.
        self.__closing: bool = False

        self.__extra_attributes = MappingProxyType(socket_tools._get_socket_extra(socket, wrap_in_proxy=False))

    def __del__(self, *, _warn: _utils.WarnCallback = warnings.warn) -> None:
        try:
            endpoint = self.__endpoint
        except AttributeError:  # pragma: no cover
            # Technically possible but not with the common usage because this constructor does not raise.
            return
        if not endpoint.is_closing():
            _warn(f"unclosed transport {self!r}", ResourceWarning, source=self)
            endpoint.close_nowait()

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

    def backend(self) -> AsyncBackend:
        return self.__backend

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__extra_attributes
