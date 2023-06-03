# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""asyncio engine for easynetwork.api_async
"""

from __future__ import annotations

__all__ = ["AsyncioBackend"]

import asyncio
import contextvars
import functools
import inspect
import socket as _socket
from typing import TYPE_CHECKING, Any, Callable, Coroutine, NoReturn, ParamSpec, Sequence, TypeVar

from easynetwork.api_async.backend.abc import AbstractAsyncBackend
from easynetwork.api_async.backend.sniffio import current_async_library_cvar as _sniffio_current_async_library_cvar

if TYPE_CHECKING:
    import concurrent.futures
    import ssl as _ssl

    from easynetwork.api_async.backend.abc import (
        AbstractAcceptedSocket,
        AbstractAsyncDatagramSocketAdapter,
        AbstractAsyncListenerSocketAdapter,
        AbstractAsyncStreamSocketAdapter,
        AbstractTaskGroup,
        AbstractThreadsPortal,
        ICondition,
        IEvent,
        ILock,
    )

_P = ParamSpec("_P")
_T = TypeVar("_T")
_T_co = TypeVar("_T_co", covariant=True)


class AsyncioBackend(AbstractAsyncBackend):
    __slots__ = ("__use_asyncio_transport",)

    def __init__(self, *, transport: bool = True) -> None:
        self.__use_asyncio_transport: bool = bool(transport)

    @staticmethod
    def _current_asyncio_task() -> asyncio.Task[Any]:
        t: asyncio.Task[Any] | None = asyncio.current_task()
        if t is None:  # pragma: no cover
            raise RuntimeError("This function should be called within a task.")
        return t

    async def coro_yield(self) -> None:
        await asyncio.sleep(0)

    def get_cancelled_exc_class(self) -> type[BaseException]:
        return asyncio.CancelledError

    async def ignore_cancellation(self, coroutine: Coroutine[Any, Any, _T_co]) -> _T_co:
        assert inspect.iscoroutine(coroutine), "Expected a coroutine object"
        task: asyncio.Task[_T_co] = asyncio.create_task(coroutine)

        # This task must be unregistered in order not to be cancelled by runner at event loop shutdown
        asyncio._unregister_task(task)

        try:
            return await self._cancel_shielded_wait_asyncio_future(task)
        finally:
            del task

    async def wait_for(self, coroutine: Coroutine[Any, Any, _T_co], timeout: float | None) -> _T_co:
        assert inspect.iscoroutine(coroutine), "Expected a coroutine object"

        async with asyncio.timeout(timeout):
            return await coroutine

    @classmethod
    async def _cancel_shielded_wait_asyncio_future(cls, future: asyncio.Future[_T_co]) -> _T_co:
        current_task: asyncio.Task[Any] = cls._current_asyncio_task()
        cancelling: int = current_task.cancelling()

        try:
            while True:
                if future.done():
                    return future.result()
                try:
                    await asyncio.wait({future})
                except asyncio.CancelledError:
                    assert current_task.cancelling() > cancelling
                    while current_task.uncancel() > cancelling:
                        continue
        finally:
            del current_task, future

    def current_time(self) -> float:
        loop = asyncio.get_running_loop()
        return loop.time()

    async def sleep(self, delay: float) -> None:
        return await asyncio.sleep(delay)

    async def sleep_forever(self) -> NoReturn:
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
        local_address: tuple[str, int] | None = None,
        happy_eyeballs_delay: float | None = None,
    ) -> AbstractAsyncStreamSocketAdapter:
        assert host is not None, "Expected 'host' to be a str"
        assert port is not None, "Expected 'port' to be an int"

        if happy_eyeballs_delay is not None:
            self._check_asyncio_transport("'happy_eyeballs_delay' option")

        if not self.__use_asyncio_transport:
            from ._utils import create_connection
            from .stream.socket import RawStreamSocketAdapter

            loop = asyncio.get_running_loop()

            socket = await create_connection(host, port, loop, local_address=local_address)
            return RawStreamSocketAdapter(socket, loop)

        from easynetwork.tools.socket import MAX_STREAM_BUFSIZE

        from .stream.socket import AsyncioTransportStreamSocketAdapter

        if happy_eyeballs_delay is None:
            reader, writer = await asyncio.open_connection(
                host,
                port,
                local_addr=local_address,
                limit=MAX_STREAM_BUFSIZE,
            )
        else:
            reader, writer = await asyncio.open_connection(
                host,
                port,
                local_addr=local_address,
                happy_eyeballs_delay=happy_eyeballs_delay,
                limit=MAX_STREAM_BUFSIZE,
            )
        return AsyncioTransportStreamSocketAdapter(reader, writer)

    async def create_ssl_over_tcp_connection(
        self,
        host: str,
        port: int,
        ssl_context: _ssl.SSLContext,
        *,
        server_hostname: str | None,
        ssl_handshake_timeout: float,
        ssl_shutdown_timeout: float,
        local_address: tuple[str, int] | None = None,
        happy_eyeballs_delay: float | None = None,
    ) -> AbstractAsyncStreamSocketAdapter:
        self._check_ssl_support()
        self.__verify_ssl_context(ssl_context)

        from easynetwork.tools.socket import MAX_STREAM_BUFSIZE

        from .stream.socket import AsyncioTransportStreamSocketAdapter

        if happy_eyeballs_delay is None:
            reader, writer = await asyncio.open_connection(
                host,
                port,
                ssl=ssl_context,
                server_hostname=server_hostname,
                ssl_handshake_timeout=float(ssl_handshake_timeout),
                ssl_shutdown_timeout=float(ssl_shutdown_timeout),
                local_addr=local_address,
                limit=MAX_STREAM_BUFSIZE,
            )
        else:
            reader, writer = await asyncio.open_connection(
                host,
                port,
                ssl=ssl_context,
                server_hostname=server_hostname,
                ssl_handshake_timeout=float(ssl_handshake_timeout),
                ssl_shutdown_timeout=float(ssl_shutdown_timeout),
                local_addr=local_address,
                happy_eyeballs_delay=happy_eyeballs_delay,
                limit=MAX_STREAM_BUFSIZE,
            )
        return AsyncioTransportStreamSocketAdapter(reader, writer)

    async def wrap_tcp_client_socket(self, socket: _socket.socket) -> AbstractAsyncStreamSocketAdapter:
        assert socket is not None, "Expected 'socket' to be a socket.socket instance"
        socket.setblocking(False)

        if not self.__use_asyncio_transport:
            from .stream.socket import RawStreamSocketAdapter

            return RawStreamSocketAdapter(socket, asyncio.get_running_loop())

        from easynetwork.tools.socket import MAX_STREAM_BUFSIZE

        from .stream.socket import AsyncioTransportStreamSocketAdapter

        reader, writer = await asyncio.open_connection(sock=socket, limit=MAX_STREAM_BUFSIZE)
        return AsyncioTransportStreamSocketAdapter(reader, writer)

    async def wrap_ssl_over_tcp_client_socket(
        self,
        socket: _socket.socket,
        ssl_context: _ssl.SSLContext,
        *,
        server_hostname: str,
        ssl_handshake_timeout: float,
        ssl_shutdown_timeout: float,
    ) -> AbstractAsyncStreamSocketAdapter:
        self._check_ssl_support()
        self.__verify_ssl_context(ssl_context)

        assert socket is not None, "Expected 'socket' to be a socket.socket instance"
        socket.setblocking(False)

        from easynetwork.tools.socket import MAX_STREAM_BUFSIZE

        from .stream.socket import AsyncioTransportStreamSocketAdapter

        reader, writer = await asyncio.open_connection(
            sock=socket,
            ssl=ssl_context,
            server_hostname=server_hostname,
            ssl_handshake_timeout=float(ssl_handshake_timeout),
            ssl_shutdown_timeout=float(ssl_shutdown_timeout),
            limit=MAX_STREAM_BUFSIZE,
        )
        return AsyncioTransportStreamSocketAdapter(reader, writer)

    async def create_tcp_listeners(
        self,
        host: str | Sequence[str] | None,
        port: int,
        backlog: int,
        *,
        family: int = 0,
        reuse_port: bool = False,
    ) -> Sequence[AbstractAsyncListenerSocketAdapter]:
        from .stream.listener import AcceptedSocket

        return await self._create_tcp_listeners(
            host,
            port,
            backlog,
            functools.partial(AcceptedSocket, use_asyncio_transport=self.__use_asyncio_transport),
            family=family,
            reuse_port=reuse_port,
        )

    async def create_ssl_over_tcp_listeners(
        self,
        host: str | Sequence[str] | None,
        port: int,
        backlog: int,
        ssl_context: _ssl.SSLContext,
        ssl_handshake_timeout: float,
        ssl_shutdown_timeout: float,
        *,
        family: int = 0,
        reuse_port: bool = False,
    ) -> Sequence[AbstractAsyncListenerSocketAdapter]:
        self._check_ssl_support()
        self.__verify_ssl_context(ssl_context)

        from .stream.listener import AcceptedSSLSocket

        return await self._create_tcp_listeners(
            host,
            port,
            backlog,
            functools.partial(
                AcceptedSSLSocket,
                ssl_context=ssl_context,
                ssl_handshake_timeout=float(ssl_handshake_timeout),
                ssl_shutdown_timeout=float(ssl_shutdown_timeout),
            ),
            family=family,
            reuse_port=reuse_port,
        )

    async def _create_tcp_listeners(
        self,
        host: str | Sequence[str] | None,
        port: int,
        backlog: int,
        accepted_socket_factory: Callable[[_socket.socket, asyncio.AbstractEventLoop], AbstractAcceptedSocket],
        *,
        family: int,
        reuse_port: bool,
    ) -> Sequence[AbstractAsyncListenerSocketAdapter]:
        assert port is not None, "Expected 'port' to be an int"

        import os
        import sys
        from itertools import chain

        from easynetwork.tools._utils import open_listener_sockets_from_getaddrinfo_result

        from ._utils import _ensure_resolved

        loop = asyncio.get_running_loop()

        reuse_address: bool = os.name not in ("nt", "cygwin") and sys.platform != "cygwin"
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
                    *[_ensure_resolved(host, port, family, _socket.SOCK_STREAM, loop, flags=_socket.AI_PASSIVE) for host in hosts]
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

        return [ListenerSocketAdapter(sock, loop, accepted_socket_factory) for sock in sockets]

    async def create_udp_endpoint(
        self,
        *,
        family: int = 0,
        local_address: tuple[str | None, int] | None = None,
        remote_address: tuple[str, int] | None = None,
        reuse_port: bool = False,
    ) -> AbstractAsyncDatagramSocketAdapter:
        from ._utils import create_datagram_socket

        socket = await create_datagram_socket(
            loop=asyncio.get_running_loop(),
            family=family,
            local_address=local_address,
            remote_address=remote_address,
            reuse_port=reuse_port,
        )

        return await self.wrap_udp_socket(socket)

    async def wrap_udp_socket(self, socket: _socket.socket) -> AbstractAsyncDatagramSocketAdapter:
        assert socket is not None, "Expected 'socket' to be a socket.socket instance"
        socket.setblocking(False)

        if not self.__use_asyncio_transport:
            from .datagram.socket import RawDatagramSocketAdapter

            return RawDatagramSocketAdapter(socket, asyncio.get_running_loop())

        from .datagram.endpoint import create_datagram_endpoint
        from .datagram.socket import AsyncioTransportDatagramSocketAdapter

        endpoint = await create_datagram_endpoint(socket=socket)
        return AsyncioTransportDatagramSocketAdapter(endpoint)

    def create_lock(self) -> ILock:
        return asyncio.Lock()

    def create_event(self) -> IEvent:
        return asyncio.Event()

    def create_condition_var(self, lock: ILock | None = None) -> ICondition:
        if lock is not None:
            assert isinstance(lock, asyncio.Lock)

        return asyncio.Condition(lock)

    async def run_in_thread(self, __func: Callable[_P, _T], /, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        loop = asyncio.get_running_loop()
        ctx = contextvars.copy_context()

        if _sniffio_current_async_library_cvar is not None:
            ctx.run(_sniffio_current_async_library_cvar.set, None)

        func_call: Callable[..., _T] = functools.partial(ctx.run, __func, *args, **kwargs)  # type: ignore[assignment]
        future = loop.run_in_executor(None, func_call)
        del func_call, __func, args, kwargs
        try:
            return await self._cancel_shielded_wait_asyncio_future(future)
        finally:
            del future

    def create_threads_portal(self) -> AbstractThreadsPortal:
        from .threads import ThreadsPortal

        return ThreadsPortal()

    async def wait_future(self, future: concurrent.futures.Future[_T_co]) -> _T_co:
        future_wrapper = asyncio.wrap_future(future)

        if not future.running():  # There is a chance to cancel the future
            current_task: asyncio.Task[Any] = self._current_asyncio_task()
            cancelling: int = current_task.cancelling()
            try:
                await asyncio.wait({future_wrapper})
            except asyncio.CancelledError:
                if future.cancel():
                    raise
                # future.cancel() failed, that means future.set_running_or_notify_cancel() has been called
                # and sets future in RUNNING state.
                # This future cannot be cancelled anymore, therefore it must be awaited.
                assert current_task.cancelling() > cancelling
                while current_task.uncancel() > cancelling:
                    continue
            else:
                try:
                    assert future.done()
                    return future.result()
                finally:
                    del future_wrapper, future
            finally:
                del current_task

        try:
            del future
            return await self._cancel_shielded_wait_asyncio_future(future_wrapper)
        finally:
            del future_wrapper

    def use_asyncio_transport(self) -> bool:
        return self.__use_asyncio_transport

    def _check_asyncio_transport(self, context: str) -> None:
        transport = self.__use_asyncio_transport
        if not transport:
            raise ValueError(f"{context} not supported with {transport=}")

    def _check_ssl_support(self) -> None:
        self._check_asyncio_transport("SSL/TLS")

    def __verify_ssl_context(self, ctx: _ssl.SSLContext) -> None:
        import ssl

        if not isinstance(ctx, ssl.SSLContext):
            raise ValueError(f"Expected a ssl.SSLContext instance, got {ctx!r}")
