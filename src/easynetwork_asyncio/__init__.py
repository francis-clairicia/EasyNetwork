# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""asyncio engine for easynetwork.async_api
"""

from __future__ import annotations

__all__ = ["AsyncioBackend"]  # type: list[str]

__version__ = "1.0.0"

import concurrent.futures
from typing import TYPE_CHECKING, TypeVar, final

from easynetwork.async_api.backend.abc import AbstractAsyncBackend

if TYPE_CHECKING:
    import socket as _socket

    from easynetwork.async_api.backend.abc import AbstractDatagramSocketAdapter, AbstractStreamSocketAdapter, ILock

_T = TypeVar("_T")


@final
class AsyncioBackend(AbstractAsyncBackend):
    __slots__ = ()

    async def coro_yield(self) -> None:
        import asyncio

        return await asyncio.sleep(0)

    async def create_tcp_connection(
        self,
        host: str,
        port: int,
        *,
        family: int = 0,
        source_address: tuple[str, int] | None = None,
        happy_eyeballs_delay: float | None = None,
    ) -> AbstractStreamSocketAdapter:
        assert host is not None, "Expected 'host' to be a str"
        assert port is not None, "Expected 'port' to be an int"

        if happy_eyeballs_delay is None:
            happy_eyeballs_delay = 0.25  # Recommended value (c.f. https://tools.ietf.org/html/rfc6555)

        import asyncio

        from easynetwork.tools.socket import MAX_STREAM_BUFSIZE

        from .stream import StreamSocketAdapter

        reader, writer = await asyncio.open_connection(
            host,
            port,
            family=family,
            local_address=source_address,
            happy_eyeballs_delay=happy_eyeballs_delay,
            limit=MAX_STREAM_BUFSIZE,
        )
        return StreamSocketAdapter(self, reader, writer)

    async def wrap_tcp_socket(self, socket: _socket.socket) -> AbstractStreamSocketAdapter:
        assert socket is not None, "Expected 'socket' to be a socket.socket instance"
        socket.setblocking(False)

        import asyncio

        from easynetwork.tools.socket import MAX_STREAM_BUFSIZE

        from .stream import StreamSocketAdapter

        reader, writer = await asyncio.open_connection(sock=socket, limit=MAX_STREAM_BUFSIZE)
        return StreamSocketAdapter(self, reader, writer)

    async def create_udp_endpoint(
        self,
        *,
        family: int = 0,
        local_address: tuple[str, int] | None = None,
        remote_address: tuple[str, int] | None = None,
        reuse_port: bool = False,
    ) -> AbstractDatagramSocketAdapter:
        from .datagram import DatagramSocketAdapter, create_datagram_endpoint

        endpoint = await create_datagram_endpoint(
            family=family,
            local_address=local_address,
            remote_address=remote_address,
            reuse_port=reuse_port,
        )
        return DatagramSocketAdapter(self, endpoint)

    async def wrap_udp_socket(self, socket: _socket.socket) -> AbstractDatagramSocketAdapter:
        assert socket is not None, "Expected 'socket' to be a socket.socket instance"
        socket.setblocking(False)

        from .datagram import DatagramSocketAdapter, create_datagram_endpoint

        endpoint = await create_datagram_endpoint(socket=socket)
        return DatagramSocketAdapter(self, endpoint)

    def create_lock(self) -> ILock:
        import asyncio

        return asyncio.Lock()

    async def wait_future(self, future: concurrent.futures.Future[_T]) -> _T:
        import asyncio

        return await asyncio.wrap_future(future)
