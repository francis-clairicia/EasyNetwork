# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""asyncio engine for easynetwork.async_ref
"""

from __future__ import annotations

__all__ = ["AsyncIOBackend"]  # type: list[str]

__version__ = "1.0.0"

from typing import TYPE_CHECKING, final

from easynetwork.async_api.backend import AbstractAsyncBackend

if TYPE_CHECKING:
    import socket as _socket

    from easynetwork.async_api.backend import AbstractDatagramSocketAdapter, AbstractStreamSocketAdapter, ILock


@final
class AsyncIOBackend(AbstractAsyncBackend):
    __slots__ = ()

    async def coro_yield(self) -> None:
        import asyncio

        return await asyncio.sleep(0)

    async def create_tcp_connection(
        self,
        host: str,
        port: int,
        *,
        source_address: tuple[str, int] | None = None,
        happy_eyeballs_delay: float | None = None,
    ) -> AbstractStreamSocketAdapter:
        assert host is not None, "Expected 'host' to be a str"
        assert port is not None, "Expected 'port' to be an int"

        if happy_eyeballs_delay is None:
            happy_eyeballs_delay = 0.25  # Recommended value (c.f. https://tools.ietf.org/html/rfc6555)
        elif happy_eyeballs_delay == float("+inf"):
            happy_eyeballs_delay = None

        import asyncio

        from easynetwork.tools.socket import MAX_STREAM_BUFSIZE

        from .stream import StreamSocketAdapter

        reader, writer = await asyncio.open_connection(
            host,
            port,
            local_address=source_address,
            happy_eyeballs_delay=happy_eyeballs_delay,
            limit=MAX_STREAM_BUFSIZE,
        )

        return StreamSocketAdapter(self, reader, writer)

    async def wrap_tcp_socket(self, socket: _socket.socket) -> AbstractStreamSocketAdapter:
        assert socket is not None, "Expected 'socket' to be a socket.socket instance"

        import asyncio

        from easynetwork.tools.socket import MAX_STREAM_BUFSIZE

        from .stream import StreamSocketAdapter

        reader, writer = await asyncio.open_connection(sock=socket, limit=MAX_STREAM_BUFSIZE)

        return StreamSocketAdapter(self, reader, writer)

    async def create_udp_endpoint(
        self,
        *,
        local_address: tuple[str, int] | None = None,
        remote_address: tuple[str, int] | None = None,
        reuse_port: bool = False,
    ) -> AbstractDatagramSocketAdapter:
        from .datagram import DatagramSocketAdapter, create_datagram_endpoint

        endpoint = await create_datagram_endpoint(
            local_address=local_address,
            remote_address=remote_address,
            reuse_port=reuse_port,
        )
        return DatagramSocketAdapter(self, endpoint)

    async def wrap_udp_socket(self, socket: _socket.socket) -> AbstractDatagramSocketAdapter:
        assert socket is not None, "Expected 'socket' to be a socket.socket instance"

        from .datagram import DatagramSocketAdapter, create_datagram_endpoint

        endpoint = await create_datagram_endpoint(socket=socket)
        return DatagramSocketAdapter(self, endpoint)

    def create_lock(self) -> ILock:
        import asyncio

        return asyncio.Lock()
