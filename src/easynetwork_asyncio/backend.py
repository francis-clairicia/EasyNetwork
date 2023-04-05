# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""asyncio engine for easynetwork.api_async
"""

from __future__ import annotations

__all__ = ["AsyncioBackend"]  # type: list[str]

import concurrent.futures
from typing import TYPE_CHECKING, Any, Sequence, TypeVar, final

from easynetwork.api_async.backend.abc import AbstractAsyncBackend

if TYPE_CHECKING:
    import asyncio
    import socket as _socket

    from easynetwork.api_async.backend.abc import (
        AbstractAsyncDatagramSocketAdapter,
        AbstractAsyncListenerSocketAdapter,
        AbstractAsyncStreamSocketAdapter,
        AbstractTaskGroup,
        ILock,
    )

_T = TypeVar("_T")


@final
class AsyncioBackend(AbstractAsyncBackend):
    __slots__ = ()

    async def coro_yield(self) -> None:
        import asyncio

        return await asyncio.sleep(0)

    def create_task_group(self) -> AbstractTaskGroup:
        from .tools.tasks import TaskGroup

        return TaskGroup()

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

        from .stream.socket import StreamSocketAdapter

        reader, writer = await asyncio.open_connection(
            host,
            port,
            family=family,
            local_addr=local_address,
            happy_eyeballs_delay=happy_eyeballs_delay,
            limit=MAX_STREAM_BUFSIZE,
        )
        return StreamSocketAdapter(self, reader, writer)

    async def wrap_connected_tcp_socket(self, socket: _socket.socket) -> AbstractAsyncStreamSocketAdapter:
        assert socket is not None, "Expected 'socket' to be a socket.socket instance"
        socket.setblocking(False)

        import asyncio

        from easynetwork.tools.socket import MAX_STREAM_BUFSIZE

        from .stream.socket import StreamSocketAdapter

        reader, writer = await asyncio.open_connection(sock=socket, limit=MAX_STREAM_BUFSIZE)
        return StreamSocketAdapter(self, reader, writer)

    async def create_tcp_listeners(
        self,
        host: str | Sequence[str],
        port: int,
        *,
        family: int,
        backlog: int,
        reuse_port: bool,
    ) -> Sequence[AbstractAsyncListenerSocketAdapter]:
        assert host is not None, "Expected 'host' to be a str or a sequence of str"
        assert port is not None, "Expected 'port' to be an int"

        import asyncio
        import os
        import socket as _socket
        import sys
        from itertools import chain

        from easynetwork.tools._utils import set_reuseport

        loop = asyncio.get_running_loop()

        reuse_address = os.name == "posix" and sys.platform != "cygwin"
        sockets: list[_socket.socket] = []
        hosts: Sequence[str | None]
        if host == "":
            hosts = [None]
        elif isinstance(host, str):
            hosts = [host]
        else:
            hosts = host

        infos: set[tuple[int, int, int, str, tuple[Any, ...]]] = set(
            chain.from_iterable(
                asyncio.gather(*[self._create_tcp_listener_getaddrinfo(host, port, family, loop) for host in hosts])
            )
        )

        completed = False
        try:
            for res in infos:
                af, socktype, proto, canonname, sa = res
                try:
                    sock = _socket.socket(af, socktype, proto)
                except OSError:
                    # Assume it's a bad family/type/protocol combination.
                    continue
                sockets.append(sock)
                if reuse_address:
                    sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, True)
                if reuse_port:
                    set_reuseport(sock)
                # Disable IPv4/IPv6 dual stack support (enabled by
                # default on Linux) which makes a single socket
                # listen on both address families.
                if _socket.has_ipv6 and af == _socket.AF_INET6 and hasattr(_socket, "IPPROTO_IPV6"):
                    sock.setsockopt(_socket.IPPROTO_IPV6, _socket.IPV6_V6ONLY, True)
                try:
                    sock.bind(sa)
                except OSError as err:
                    raise OSError(
                        err.errno, "error while attempting " "to bind on address %r: %s" % (sa, err.strerror.lower())
                    ) from None
                sock.listen(backlog)
            completed = True
        finally:
            if not completed:
                for sock in sockets:
                    sock.close()

        from .stream.listener import ListenerSocketAdapter

        return [ListenerSocketAdapter(self, sock, loop=loop) for sock in sockets]

    @staticmethod
    async def _create_tcp_listener_getaddrinfo(
        host: str | None,
        port: int,
        family: int,
        loop: asyncio.AbstractEventLoop,
    ) -> Sequence[tuple[int, int, int, str, tuple[Any, ...]]]:
        from socket import SOCK_STREAM

        from easynetwork.tools._utils import ipaddr_info

        resolved_info = ipaddr_info(host, port, family=family, type=SOCK_STREAM, proto=0)
        if resolved_info is not None:
            return [resolved_info]

        info = await loop.getaddrinfo(host, port, family=family, type=SOCK_STREAM, proto=0)
        if not info:
            raise OSError(f"getaddrinfo({host!r}) returned empty list")
        return info

    async def create_udp_endpoint(
        self,
        *,
        family: int,
        local_address: tuple[str, int] | None,
        remote_address: tuple[str, int] | None,
        reuse_port: bool,
    ) -> AbstractAsyncDatagramSocketAdapter:
        from .datagram.endpoint import create_datagram_endpoint
        from .datagram.socket import DatagramSocketAdapter

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

        from .datagram.endpoint import create_datagram_endpoint
        from .datagram.socket import DatagramSocketAdapter

        endpoint = await create_datagram_endpoint(socket=socket)
        return DatagramSocketAdapter(self, endpoint)

    def create_lock(self) -> ILock:
        import asyncio

        return asyncio.Lock()

    async def wait_future(self, future: concurrent.futures.Future[_T]) -> _T:
        import asyncio

        return await asyncio.wrap_future(future)
