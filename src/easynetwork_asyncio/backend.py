# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""asyncio engine for easynetwork.api_async
"""

from __future__ import annotations

__all__ = ["AsyncioBackend"]  # type: list[str]

import socket as _socket
from typing import TYPE_CHECKING, Any, Callable, Coroutine, NoReturn, ParamSpec, Sequence, TypeVar, final

from easynetwork.api_async.backend.abc import AbstractAsyncBackend

if TYPE_CHECKING:
    import asyncio as _asyncio
    import concurrent.futures

    from easynetwork.api_async.backend.abc import (
        AbstractAsyncDatagramSocketAdapter,
        AbstractAsyncListenerSocketAdapter,
        AbstractAsyncStreamSocketAdapter,
        AbstractTaskGroup,
        AbstractThreadsPortal,
        IEvent,
        ILock,
    )

_P = ParamSpec("_P")
_T = TypeVar("_T")
_T_co = TypeVar("_T_co", covariant=True)


@final
class AsyncioBackend(AbstractAsyncBackend):
    __slots__ = ()

    @staticmethod
    def _current_asyncio_task() -> _asyncio.Task[Any]:
        from asyncio import current_task

        t: _asyncio.Task[Any] | None = current_task()
        if t is None:  # pragma: no cover
            raise RuntimeError("This function should be called within a task.")
        return t

    @staticmethod
    def _really_uncancel_task(task: _asyncio.Task[Any]) -> None:
        while task.uncancel() != 0:  # It must really NOT be cancelled
            continue

    async def coro_yield(self) -> None:
        return await self.sleep(0)

    async def coro_cancel(self) -> NoReturn:
        import asyncio

        # Why a 'while True' ?
        # Since 3.11 a task can be un-cancelled, and this is problematic, so just to be sure this task will be cancelled,
        # we will retry again and again until the coroutine is stopped
        while True:
            current_task: asyncio.Task[Any] = self._current_asyncio_task()

            current_task.cancel()
            await asyncio.sleep(0)

    def get_cancelled_exc_class(self) -> type[BaseException]:
        import asyncio

        return asyncio.CancelledError

    async def ignore_cancellation(self, coroutine: Coroutine[Any, Any, _T_co]) -> _T_co:
        import asyncio

        task: asyncio.Task[_T_co] = asyncio.create_task(coroutine)

        # This task must be unregistered in order not to be cancelled by runner at event loop shutdown
        asyncio._unregister_task(task)

        return await self._cancel_shielded_wait_asyncio_future(task)

    @classmethod
    async def _cancel_shielded_wait_asyncio_future(cls, future: _asyncio.Future[_T_co]) -> _T_co:
        import asyncio

        current_task: _asyncio.Task[Any] = cls._current_asyncio_task()

        while True:
            try:
                return await asyncio.shield(future)
            except asyncio.CancelledError:
                if future.done():
                    raise
                cls._really_uncancel_task(current_task)

    def current_time(self) -> float:
        import asyncio

        loop = asyncio.get_running_loop()
        return loop.time()

    async def sleep(self, delay: float) -> None:
        import asyncio

        return await asyncio.sleep(delay)

    async def sleep_forever(self) -> NoReturn:
        import asyncio

        loop = asyncio.get_running_loop()
        await loop.create_future()
        raise AssertionError("await an unused future cannot end in any other way than by cancellation")

    def create_task_group(self) -> AbstractTaskGroup:
        from .tasks import TaskGroup

        return TaskGroup()

    async def create_tcp_connection(
        self,
        host: str,
        port: int,
        *,
        family: int = 0,
        local_address: tuple[str, int] | None = None,
        happy_eyeballs_delay: float | None = None,
    ) -> AbstractAsyncStreamSocketAdapter:
        assert host is not None, "Expected 'host' to be a str"
        assert port is not None, "Expected 'port' to be an int"

        import asyncio

        from easynetwork.tools.socket import MAX_STREAM_BUFSIZE

        from .stream.socket import StreamSocketAdapter

        if happy_eyeballs_delay is None:
            reader, writer = await asyncio.open_connection(
                host,
                port,
                family=family,
                local_addr=local_address,
                limit=MAX_STREAM_BUFSIZE,
            )
        else:
            reader, writer = await asyncio.open_connection(
                host,
                port,
                family=family,
                local_addr=local_address,
                happy_eyeballs_delay=happy_eyeballs_delay,
                limit=MAX_STREAM_BUFSIZE,
            )
        return StreamSocketAdapter(reader, writer)

    async def wrap_tcp_client_socket(self, socket: _socket.socket) -> AbstractAsyncStreamSocketAdapter:
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
        family: int = 0,
        backlog: int = 100,
        reuse_port: bool = False,
    ) -> Sequence[AbstractAsyncListenerSocketAdapter]:
        assert port is not None, "Expected 'port' to be an int"

        import asyncio
        import os
        import sys
        from itertools import chain

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
                    *[
                        self._ensure_resolved(host, port, family, _socket.SOCK_STREAM, loop, flags=_socket.AI_PASSIVE)
                        for host in hosts
                    ]
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
        loop: _asyncio.AbstractEventLoop,
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
        family: int = 0,
        local_address: tuple[str | None, int] | None = None,
        remote_address: tuple[str, int] | None = None,
        reuse_port: bool = False,
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

    def create_threads_portal(self) -> AbstractThreadsPortal:
        from .threads import ThreadsPortal

        return ThreadsPortal()

    async def wait_future(self, future: concurrent.futures.Future[_T_co]) -> _T_co:
        import asyncio

        if not future.running():  # There is a chance to cancel the future
            try:
                return await asyncio.wrap_future(future)
            except asyncio.CancelledError:
                if future.done():  # asyncio.CancelledError raised by either future.cancelled() or future.exception()
                    raise
                self._really_uncancel_task(self._current_asyncio_task())

        return await self._cancel_shielded_wait_asyncio_future(asyncio.wrap_future(future))
