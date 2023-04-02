# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""asyncio engine for easynetwork.api_async
"""

from __future__ import annotations

__all__ = ["AsyncioBackend"]  # type: list[str]

__version__ = "1.0.0"

import concurrent.futures
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Sequence, TypeVar, final

from easynetwork.api_async.backend.abc import AbstractAsyncBackend

if TYPE_CHECKING:
    import socket as _socket

    from easynetwork.api_async.backend.abc import (
        AbstractAsyncDatagramServerAdapter,
        AbstractAsyncDatagramSocketAdapter,
        AbstractAsyncServerAdapter,
        AbstractAsyncStreamSocketAdapter,
        ILock,
    )

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
        family: int,
        local_address: tuple[str, int] | None,
        happy_eyeballs_delay: float | None,
    ) -> AbstractAsyncStreamSocketAdapter:
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
            local_addr=local_address,
            happy_eyeballs_delay=happy_eyeballs_delay,
            limit=MAX_STREAM_BUFSIZE,
        )
        return StreamSocketAdapter(self, reader, writer)

    async def wrap_tcp_socket(self, socket: _socket.socket) -> AbstractAsyncStreamSocketAdapter:
        assert socket is not None, "Expected 'socket' to be a socket.socket instance"
        socket.setblocking(False)

        import asyncio

        from easynetwork.tools.socket import MAX_STREAM_BUFSIZE

        from .stream import StreamSocketAdapter

        reader, writer = await asyncio.open_connection(sock=socket, limit=MAX_STREAM_BUFSIZE)
        return StreamSocketAdapter(self, reader, writer)

    async def create_tcp_server(
        self,
        client_connected_cb: Callable[[AbstractAsyncStreamSocketAdapter], Coroutine[Any, Any, Any]],
        host: str | Sequence[str],
        port: int,
        *,
        family: int,
        backlog: int | None,
        reuse_address: bool,
        reuse_port: bool,
    ) -> AbstractAsyncServerAdapter:
        assert host is not None, "Expected 'host' to be a str or a sequence of str"
        assert port is not None, "Expected 'port' to be an int"

        import asyncio

        from easynetwork.tools.socket import MAX_STREAM_BUFSIZE

        from .stream import Server, StreamSocketAdapter

        async def asyncio_client_connected_cb(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            socket = StreamSocketAdapter(self, reader, writer)
            try:
                async with socket:
                    await client_connected_cb(socket)
            except asyncio.CancelledError:
                try:
                    await socket.abort()
                finally:
                    raise

        asyncio_server: asyncio.Server = await asyncio.start_server(
            asyncio_client_connected_cb,
            host,
            port,
            limit=MAX_STREAM_BUFSIZE,
            family=family,
            backlog=backlog,
            reuse_address=reuse_address,
            reuse_port=reuse_port,
        )
        return Server(self, asyncio_server)

    async def create_udp_endpoint(
        self,
        *,
        family: int,
        local_address: tuple[str, int] | None,
        remote_address: tuple[str, int] | None,
        reuse_port: bool,
    ) -> AbstractAsyncDatagramSocketAdapter:
        from .datagram import DatagramSocketAdapter, create_datagram_endpoint

        endpoint = await create_datagram_endpoint(
            family=family,
            local_addr=local_address,
            remote_addr=remote_address,
            reuse_port=reuse_port,
        )
        return DatagramSocketAdapter(self, endpoint)

    async def wrap_udp_socket(self, socket: _socket.socket) -> AbstractAsyncDatagramSocketAdapter:
        assert socket is not None, "Expected 'socket' to be a socket.socket instance"
        socket.setblocking(False)

        from .datagram import DatagramSocketAdapter, create_datagram_endpoint

        endpoint = await create_datagram_endpoint(socket=socket)
        return DatagramSocketAdapter(self, endpoint)

    async def create_udp_server(
        self,
        datagram_received_cb: Callable[[bytes, tuple[Any, ...]], Coroutine[Any, Any, Any]],
        error_received_cb: Callable[[Exception], Coroutine[Any, Any, Any]],
        host: str,
        port: int,
        *,
        family: int,
        reuse_port: bool,
    ) -> AbstractAsyncDatagramServerAdapter:
        from .datagram import DatagramServer, create_datagram_endpoint

        endpoint = await create_datagram_endpoint(local_addr=(host, port), family=family, reuse_port=reuse_port)
        return DatagramServer(self, endpoint, datagram_received_cb, error_received_cb)

    def create_lock(self) -> ILock:
        import asyncio

        return asyncio.Lock()

    async def wait_future(self, future: concurrent.futures.Future[_T]) -> _T:
        import asyncio

        return await asyncio.wrap_future(future)
