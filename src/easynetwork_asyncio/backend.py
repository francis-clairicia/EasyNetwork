# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""asyncio engine for easynetwork.api_async
"""

from __future__ import annotations

__all__ = ["AsyncioBackend"]  # type: list[str]

import concurrent.futures
import socket as _socket
from typing import TYPE_CHECKING, Any, Callable, Coroutine, ParamSpec, Sequence, TypeVar, final

from easynetwork.api_async.backend.abc import AbstractAsyncBackend

if TYPE_CHECKING:
    import asyncio

    from easynetwork.api_async.backend.abc import (
        AbstractAsyncDatagramSocketAdapter,
        AbstractAsyncListenerSocketAdapter,
        AbstractAsyncStreamSocketAdapter,
        AbstractTaskGroup,
        IEvent,
        ILock,
    )

_P = ParamSpec("_P")
_T = TypeVar("_T")
_T_co = TypeVar("_T_co", covariant=True)


@final
class AsyncioBackend(AbstractAsyncBackend):
    __slots__ = ("__bound_loop", "__thread_id")

    def __init__(self) -> None:
        super().__init__()

        import asyncio
        import threading

        self.__bound_loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        self.__thread_id: int = threading.get_ident()

    async def coro_yield(self) -> None:
        return await self.sleep(0)

    def current_time(self) -> float:
        import asyncio

        loop = asyncio.get_running_loop()
        return loop.time()

    async def sleep(self, delay: float) -> None:
        import asyncio

        return await asyncio.sleep(delay)

    def create_task_group(self) -> AbstractTaskGroup:
        from .tasks import TaskGroup

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
        return StreamSocketAdapter(reader, writer)

    async def wrap_connected_tcp_socket(self, socket: _socket.socket) -> AbstractAsyncStreamSocketAdapter:
        assert socket is not None, "Expected 'socket' to be a socket.socket instance"
        socket.setblocking(False)

        import asyncio

        from easynetwork.tools.socket import MAX_STREAM_BUFSIZE

        from .stream.socket import StreamSocketAdapter

        reader, writer = await asyncio.open_connection(sock=socket, limit=MAX_STREAM_BUFSIZE)
        return StreamSocketAdapter(reader, writer)

    async def create_tcp_listeners(
        self,
        host: str | Sequence[str] | None,
        port: int,
        *,
        family: int,
        backlog: int,
        reuse_port: bool,
    ) -> Sequence[AbstractAsyncListenerSocketAdapter]:
        assert port is not None, "Expected 'port' to be an int"

        import asyncio
        import os
        import sys
        from itertools import chain
        from socket import AI_PASSIVE, SOCK_STREAM

        from easynetwork.tools._utils import open_listener_sockets_from_getaddrinfo_result

        loop = asyncio.get_running_loop()

        reuse_address = os.name == "posix" and sys.platform != "cygwin"
        hosts: Sequence[str | None]
        if host == "" or host is None:
            hosts = [None]
        elif isinstance(host, str):
            hosts = [host]
        else:
            hosts = host

        infos: set[tuple[int, int, int, str, tuple[Any, ...]]] = set(
            chain.from_iterable(
                await asyncio.gather(
                    *[self._ensure_resolved(host, port, family, SOCK_STREAM, loop, flags=AI_PASSIVE) for host in hosts]
                )
            )
        )

        sockets: list[_socket.socket] = open_listener_sockets_from_getaddrinfo_result(
            infos,
            backlog=backlog,
            reuse_address=reuse_address,
            reuse_port=reuse_port,
        )

        from .stream.listener import ListenerSocketAdapter

        return [ListenerSocketAdapter(sock, loop=loop) for sock in sockets]

    @staticmethod
    async def _ensure_resolved(
        host: str | None,
        port: int,
        family: int,
        type: int,
        loop: asyncio.AbstractEventLoop,
        proto: int = 0,
        flags: int = 0,
    ) -> Sequence[tuple[int, int, int, str, tuple[Any, ...]]]:
        info = await loop.getaddrinfo(host, port, family=family, type=type, proto=proto, flags=flags)
        if not info:
            raise OSError(f"getaddrinfo({host!r}) returned empty list")
        return info

    @staticmethod
    def _ensure_host(address: tuple[str | None, int], family: int) -> tuple[str, int]:
        host, port = address
        if not host:
            match family:
                case _socket.AF_INET | _socket.AF_UNSPEC:
                    host = "0.0.0.0"
                case _socket.AF_INET6:
                    host = "::"
                case _:  # pragma: no cover
                    raise OSError("Only AF_INET and AF_INET6 families are supported")
        address = (host, port)
        return address

    async def create_udp_endpoint(
        self,
        *,
        family: int,
        local_address: tuple[str | None, int] | None,
        remote_address: tuple[str, int] | None,
        reuse_port: bool,
    ) -> AbstractAsyncDatagramSocketAdapter:
        from .datagram.endpoint import create_datagram_endpoint
        from .datagram.socket import DatagramSocketAdapter

        if local_address is not None:
            local_address = self._ensure_host(local_address, family)

        endpoint = await create_datagram_endpoint(
            family=family,
            local_addr=local_address,
            remote_addr=remote_address,
            reuse_port=reuse_port,
        )
        return DatagramSocketAdapter(endpoint)

    async def wrap_udp_socket(self, socket: _socket.socket) -> AbstractAsyncDatagramSocketAdapter:
        assert socket is not None, "Expected 'socket' to be a socket.socket instance"
        socket.setblocking(False)

        from .datagram.endpoint import create_datagram_endpoint
        from .datagram.socket import DatagramSocketAdapter

        endpoint = await create_datagram_endpoint(socket=socket)
        return DatagramSocketAdapter(endpoint)

    def create_lock(self) -> ILock:
        import asyncio

        return asyncio.Lock()

    def create_event(self) -> IEvent:
        import asyncio

        return asyncio.Event()

    async def run_in_thread(self, __func: Callable[_P, _T], /, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        import asyncio

        return await asyncio.to_thread(__func, *args, **kwargs)

    def run_coroutine_from_thread(
        self,
        __coro_func: Callable[_P, Coroutine[Any, Any, _T]],
        /,
        *args: _P.args,
        **kwargs: _P.kwargs,
    ) -> _T:
        import asyncio
        import threading

        if threading.get_ident() == self.__thread_id:
            raise RuntimeError("run_coroutine_from_thread() must be called in a different OS thread")

        future = asyncio.run_coroutine_threadsafe(__coro_func(*args, **kwargs), self.__bound_loop)
        return future.result()

    async def wait_future(self, future: concurrent.futures.Future[_T_co]) -> _T_co:
        import asyncio

        return await asyncio.wrap_future(future)
