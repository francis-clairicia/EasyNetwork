# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""asyncio engine for easynetwork.async
"""

from __future__ import annotations

__all__ = ["Server"]

from typing import TYPE_CHECKING, Sequence, final

from easynetwork.api_async.backend.abc import AbstractAsyncServerAdapter
from easynetwork.tools.socket import SocketProxy

if TYPE_CHECKING:
    import asyncio
    import asyncio.trsock

    from ..backend import AsyncioBackend


@final
class Server(AbstractAsyncServerAdapter):
    __slots__ = (
        "__backend",
        "__asyncio_server",
    )

    def __init__(self, backend: AsyncioBackend, asyncio_server: asyncio.Server) -> None:
        super().__init__()
        self.__backend: AsyncioBackend = backend
        self.__asyncio_server: asyncio.Server = asyncio_server

    async def close(self) -> None:
        self.__asyncio_server.close()
        return await self.__asyncio_server.wait_closed()

    def is_serving(self) -> bool:
        return self.__asyncio_server.is_serving()

    def stop_serving(self) -> None:
        self.__asyncio_server.close()

    async def serve_forever(self) -> None:
        return await self.__asyncio_server.serve_forever()

    def get_backend(self) -> AsyncioBackend:
        return self.__backend

    def sockets(self) -> Sequence[SocketProxy]:
        return tuple(map(SocketProxy, self.__asyncio_server.sockets))
