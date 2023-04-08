# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""asyncio engine for easynetwork.async
"""

from __future__ import annotations

__all__ = ["DatagramSocketAdapter"]

from typing import TYPE_CHECKING, Any, final

from easynetwork.api_async.backend.abc import AbstractAsyncDatagramSocketAdapter

if TYPE_CHECKING:
    import asyncio.trsock

    from _typeshed import ReadableBuffer

    from .endpoint import DatagramEndpoint


@final
class DatagramSocketAdapter(AbstractAsyncDatagramSocketAdapter):
    __slots__ = ("__endpoint",)

    def __init__(self, endpoint: DatagramEndpoint) -> None:
        super().__init__()
        self.__endpoint: DatagramEndpoint = endpoint

        socket: asyncio.trsock.TransportSocket | None = endpoint.get_extra_info("socket")
        assert socket is not None, "transport must be a socket transport"

    async def close(self) -> None:
        self.__endpoint.close()
        return await self.__endpoint.wait_closed()

    async def abort(self) -> None:
        self.__endpoint.transport.abort()

    def is_closing(self) -> bool:
        return self.__endpoint.is_closing()

    def get_local_address(self) -> tuple[Any, ...]:
        return self.__endpoint.get_extra_info("sockname")

    def get_remote_address(self) -> tuple[Any, ...] | None:
        return self.__endpoint.get_extra_info("peername")

    async def recvfrom(self) -> tuple[bytes, tuple[Any, ...]]:
        return await self.__endpoint.recvfrom()

    async def sendto(self, data: ReadableBuffer, address: tuple[Any, ...] | None, /) -> None:
        with memoryview(data).toreadonly() as data_view:
            await self.__endpoint.sendto(data_view, address)

    def socket(self) -> asyncio.trsock.TransportSocket:
        socket: asyncio.trsock.TransportSocket = self.__endpoint.get_extra_info("socket")
        return socket
