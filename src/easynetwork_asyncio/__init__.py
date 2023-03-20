# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""asyncio engine for easynetwork.async
"""

from __future__ import annotations

__all__ = ["AsyncIOBackend"]  # type: list[str]

__version__ = "1.0.0"

import socket as _socket
from typing import TYPE_CHECKING, final

from easynetwork.asyncio.backend import AbstractAsyncBackend

if TYPE_CHECKING:
    from easynetwork.asyncio.backend import AbstractDatagramSocketAdapter, AbstractStreamSocketAdapter


@final
class AsyncIOBackend(AbstractAsyncBackend):
    __slots__ = ()

    async def create_tcp_connection(
        self,
        host: str,
        port: int,
        *,
        family: int = 0,
        proto: int = 0,
        source_address: tuple[str, int] | None = None,
    ) -> AbstractStreamSocketAdapter:
        assert isinstance(host, str), "Expected 'host' to be a str"
        assert isinstance(port, int), "Expected 'port' to be an int"

        import asyncio

        from easynetwork.tools.socket import MAX_STREAM_BUFSIZE

        from .stream import TransportStreamSocket

        reader, writer = await asyncio.open_connection(
            host,
            port,
            family=family,
            proto=proto,
            local_address=source_address,
            limit=MAX_STREAM_BUFSIZE,
        )

        return TransportStreamSocket(self, reader, writer)

    async def wrap_tcp_socket(self, socket: _socket.socket) -> AbstractStreamSocketAdapter:
        assert isinstance(socket, _socket.socket), "Expected 'socket' to be a socket.socket instance"

        import asyncio

        from easynetwork.tools.socket import MAX_STREAM_BUFSIZE

        from .stream import TransportStreamSocket

        reader, writer = await asyncio.open_connection(sock=socket, limit=MAX_STREAM_BUFSIZE)

        return TransportStreamSocket(self, reader, writer)

    async def create_udp_endpoint(
        self,
        local_address: tuple[str, int] | None = None,
        remote_address: tuple[str, int] | None = None,
        reuse_port: bool = False,
    ) -> AbstractDatagramSocketAdapter:
        if local_address is None:
            local_address = ("", 0)

        import asyncio

        from .datagram import TransportDatagramSocket, TransportDatagramSocketProtocol

        loop = asyncio.get_running_loop()
        recv_queue: asyncio.Queue[tuple[bytes | None, _socket._RetAddress | None]] = asyncio.Queue()
        exception_queue: asyncio.Queue[Exception] = asyncio.Queue()

        transport, protocol = await loop.create_datagram_endpoint(
            lambda: TransportDatagramSocketProtocol(loop=loop, recv_queue=recv_queue, exception_queue=exception_queue),
            local_addr=local_address,
            remote_addr=remote_address,
            reuse_port=reuse_port,
        )

        return TransportDatagramSocket(self, transport, protocol, recv_queue=recv_queue, exception_queue=exception_queue)

    async def wrap_udp_socket(self, socket: _socket.socket) -> AbstractDatagramSocketAdapter:
        if socket.getsockname()[1] == 0:
            socket.bind(("", 0))

        import asyncio

        from .datagram import TransportDatagramSocket, TransportDatagramSocketProtocol

        loop = asyncio.get_running_loop()
        recv_queue: asyncio.Queue[tuple[bytes | None, _socket._RetAddress | None]] = asyncio.Queue()
        exception_queue: asyncio.Queue[Exception] = asyncio.Queue()

        transport, protocol = await loop.create_datagram_endpoint(
            lambda: TransportDatagramSocketProtocol(loop=loop, recv_queue=recv_queue, exception_queue=exception_queue),
            sock=socket,
        )

        return TransportDatagramSocket(self, transport, protocol, recv_queue=recv_queue, exception_queue=exception_queue)
