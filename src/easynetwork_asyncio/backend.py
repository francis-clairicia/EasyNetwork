# -*- coding: utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""asyncio engine for easynetwork.api_async
"""

from __future__ import annotations

__all__ = ["AsyncioBackend"]

import asyncio
import asyncio.base_events
import contextvars
import functools
import itertools
import os
import socket as _socket
import sys
from typing import TYPE_CHECKING, Any, AsyncContextManager, Callable, Coroutine, NoReturn, ParamSpec, Sequence, TypeVar

try:
    import ssl as _ssl
except ImportError:  # pragma: no cover
    ssl = None
else:
    ssl = _ssl
    del _ssl

from easynetwork.api_async.backend.abc import AbstractAsyncBackend
from easynetwork.api_async.backend.sniffio import current_async_library_cvar as _sniffio_current_async_library_cvar
from easynetwork.tools._utils import open_listener_sockets_from_getaddrinfo_result
from easynetwork.tools.socket import MAX_STREAM_BUFSIZE

from ._utils import _ensure_resolved, create_connection, create_datagram_socket
from .datagram.endpoint import create_datagram_endpoint
from .datagram.socket import AsyncioTransportDatagramSocketAdapter, RawDatagramSocketAdapter
from .stream.listener import AcceptedSocket, AcceptedSSLSocket, ListenerSocketAdapter
from .stream.socket import AsyncioTransportStreamSocketAdapter, RawStreamSocketAdapter
from .tasks import TaskGroup, timeout, timeout_at
from .threads import ThreadsPortal

if TYPE_CHECKING:
    import concurrent.futures
    from ssl import SSLContext as _SSLContext

    from easynetwork.api_async.backend.abc import AbstractAcceptedSocket, ILock

    from .tasks import TimeoutHandle

_P = ParamSpec("_P")
_T = TypeVar("_T")
_T_co = TypeVar("_T_co", covariant=True)


class AsyncioBackend(AbstractAsyncBackend):
    __slots__ = ("__use_asyncio_transport", "__asyncio_runner_factory")

    def __init__(self, *, transport: bool = True, runner_factory: Callable[[], asyncio.Runner] | None = None) -> None:
        self.__use_asyncio_transport: bool = bool(transport)
        self.__asyncio_runner_factory: Callable[[], asyncio.Runner] = runner_factory or asyncio.Runner

    def bootstrap(self, coro_func: Callable[..., Coroutine[Any, Any, _T]], *args: Any) -> _T:
        with self.__asyncio_runner_factory() as runner:
            return runner.run(coro_func(*args))

    @staticmethod
    def _current_asyncio_task() -> asyncio.Task[Any]:
        t: asyncio.Task[Any] | None = asyncio.current_task()
        if t is None:  # pragma: no cover
            raise RuntimeError("This function should be called within a task.")
        return t

    async def coro_yield(self) -> None:
        await asyncio.sleep(0)

    async def cancel_shielded_coro_yield(self) -> None:
        current_task: asyncio.Task[Any] = self._current_asyncio_task()
        cancelling: int = current_task.cancelling()
        try:
            await asyncio.sleep(0)
        except asyncio.CancelledError:
            assert current_task.cancelling() > cancelling
            while current_task.uncancel() > cancelling:
                continue
        finally:
            del current_task

    def get_cancelled_exc_class(self) -> type[BaseException]:
        return asyncio.CancelledError

    async def ignore_cancellation(self, coroutine: Coroutine[Any, Any, _T_co]) -> _T_co:
        assert asyncio.iscoroutine(coroutine), "Expected a coroutine object"
        task: asyncio.Task[_T_co] = asyncio.create_task(coroutine)

        # This task must be unregistered in order not to be cancelled by runner at event loop shutdown
        asyncio._unregister_task(task)

        try:
            return await self._cancel_shielded_wait_asyncio_future(task)
        finally:
            del task

    def timeout(self, delay: float) -> AsyncContextManager[TimeoutHandle]:
        return timeout(delay)

    def timeout_at(self, deadline: float) -> AsyncContextManager[TimeoutHandle]:
        return timeout_at(deadline)

    @classmethod
    async def _cancel_shielded_wait_asyncio_future(cls, future: asyncio.Future[_T_co]) -> _T_co:
        current_task: asyncio.Task[Any] = cls._current_asyncio_task()
        cancelling: int = current_task.cancelling()

        try:
            while not future.done():
                try:
                    await asyncio.wait({future})
                except asyncio.CancelledError:
                    assert current_task.cancelling() > cancelling
                    while current_task.uncancel() > cancelling:
                        continue
            return future.result()
        finally:
            del current_task, future

    def current_time(self) -> float:
        loop = asyncio.get_running_loop()
        return loop.time()

    async def sleep(self, delay: float) -> None:
        await asyncio.sleep(delay)

    async def sleep_forever(self) -> NoReturn:
        loop = asyncio.get_running_loop()
        await loop.create_future()
        raise AssertionError("await an unused future cannot end in any other way than by cancellation")

    def create_task_group(self) -> TaskGroup:
        return TaskGroup()

    async def create_tcp_connection(
        self,
        host: str,
        port: int,
        *,
        local_address: tuple[str, int] | None = None,
        happy_eyeballs_delay: float | None = None,
    ) -> AsyncioTransportStreamSocketAdapter | RawStreamSocketAdapter:
        assert host is not None, "Expected 'host' to be a str"
        assert port is not None, "Expected 'port' to be an int"

        if happy_eyeballs_delay is not None:
            self._check_asyncio_transport("'happy_eyeballs_delay' option")

        if not self.__use_asyncio_transport:
            loop = asyncio.get_running_loop()
            socket = await create_connection(host, port, loop, local_address=local_address)
            return RawStreamSocketAdapter(socket, loop)

        happy_eyeballs_delay = self._default_happy_eyeballs_delay(happy_eyeballs_delay)

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
        ssl_context: _SSLContext,
        *,
        server_hostname: str | None,
        ssl_handshake_timeout: float,
        ssl_shutdown_timeout: float,
        local_address: tuple[str, int] | None = None,
        happy_eyeballs_delay: float | None = None,
    ) -> AsyncioTransportStreamSocketAdapter:
        self._check_ssl_support()
        self.__verify_ssl_context(ssl_context)

        happy_eyeballs_delay = self._default_happy_eyeballs_delay(happy_eyeballs_delay)

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

    @staticmethod
    def _default_happy_eyeballs_delay(happy_eyeballs_delay: float | None) -> float | None:
        if happy_eyeballs_delay is None:
            running_loop = asyncio.get_running_loop()
            if isinstance(running_loop, asyncio.base_events.BaseEventLoop):  # Base class of standard implementation
                happy_eyeballs_delay = 0.25  # Recommended value by the RFC 6555
        return happy_eyeballs_delay

    async def wrap_tcp_client_socket(
        self,
        socket: _socket.socket,
    ) -> AsyncioTransportStreamSocketAdapter | RawStreamSocketAdapter:
        assert socket is not None, "Expected 'socket' to be a socket.socket instance"
        socket.setblocking(False)

        if not self.__use_asyncio_transport:
            return RawStreamSocketAdapter(socket, asyncio.get_running_loop())

        reader, writer = await asyncio.open_connection(sock=socket, limit=MAX_STREAM_BUFSIZE)
        return AsyncioTransportStreamSocketAdapter(reader, writer)

    async def wrap_ssl_over_tcp_client_socket(
        self,
        socket: _socket.socket,
        ssl_context: _SSLContext,
        *,
        server_hostname: str,
        ssl_handshake_timeout: float,
        ssl_shutdown_timeout: float,
    ) -> AsyncioTransportStreamSocketAdapter:
        self._check_ssl_support()
        self.__verify_ssl_context(ssl_context)

        assert socket is not None, "Expected 'socket' to be a socket.socket instance"
        socket.setblocking(False)

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
        reuse_port: bool = False,
    ) -> Sequence[ListenerSocketAdapter]:
        return await self._create_tcp_listeners(
            host,
            port,
            backlog,
            functools.partial(AcceptedSocket, use_asyncio_transport=self.__use_asyncio_transport),
            reuse_port=reuse_port,
        )

    async def create_ssl_over_tcp_listeners(
        self,
        host: str | Sequence[str] | None,
        port: int,
        backlog: int,
        ssl_context: _SSLContext,
        ssl_handshake_timeout: float,
        ssl_shutdown_timeout: float,
        *,
        reuse_port: bool = False,
    ) -> Sequence[ListenerSocketAdapter]:
        self._check_ssl_support()
        self.__verify_ssl_context(ssl_context)

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
            reuse_port=reuse_port,
        )

    async def _create_tcp_listeners(
        self,
        host: str | Sequence[str] | None,
        port: int,
        backlog: int,
        accepted_socket_factory: Callable[[_socket.socket, asyncio.AbstractEventLoop], AbstractAcceptedSocket],
        *,
        reuse_port: bool,
    ) -> Sequence[ListenerSocketAdapter]:
        assert port is not None, "Expected 'port' to be an int"

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
            itertools.chain.from_iterable(
                await asyncio.gather(
                    *[
                        _ensure_resolved(host, port, _socket.AF_UNSPEC, _socket.SOCK_STREAM, loop, flags=_socket.AI_PASSIVE)
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

        return [ListenerSocketAdapter(sock, loop, accepted_socket_factory) for sock in sockets]

    async def create_udp_endpoint(
        self,
        *,
        local_address: tuple[str | None, int] | None = None,
        remote_address: tuple[str, int] | None = None,
        reuse_port: bool = False,
    ) -> AsyncioTransportDatagramSocketAdapter | RawDatagramSocketAdapter:
        socket = await create_datagram_socket(
            loop=asyncio.get_running_loop(),
            local_address=local_address,
            remote_address=remote_address,
            reuse_port=reuse_port,
        )

        return await self.wrap_udp_socket(socket)

    async def wrap_udp_socket(self, socket: _socket.socket) -> AsyncioTransportDatagramSocketAdapter | RawDatagramSocketAdapter:
        assert socket is not None, "Expected 'socket' to be a socket.socket instance"
        socket.setblocking(False)

        if not self.__use_asyncio_transport:
            return RawDatagramSocketAdapter(socket, asyncio.get_running_loop())

        endpoint = await create_datagram_endpoint(socket=socket)
        return AsyncioTransportDatagramSocketAdapter(endpoint)

    def create_lock(self) -> asyncio.Lock:
        return asyncio.Lock()

    def create_event(self) -> asyncio.Event:
        return asyncio.Event()

    def create_condition_var(self, lock: ILock | None = None) -> asyncio.Condition:
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

    def create_threads_portal(self) -> ThreadsPortal:
        return ThreadsPortal()

    async def wait_future(self, future: concurrent.futures.Future[_T_co]) -> _T_co:
        try:
            if future.done():
                await self.cancel_shielded_coro_yield()
                return future.result()

            future_wrapper = asyncio.wrap_future(future)
            try:
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
                        assert future.done()
                        return future.result()
                    finally:
                        del current_task

                return await self._cancel_shielded_wait_asyncio_future(future_wrapper)
            finally:
                del future_wrapper
        finally:
            del future

    def use_asyncio_transport(self) -> bool:
        return self.__use_asyncio_transport

    def _check_asyncio_transport(self, context: str) -> None:
        transport = self.__use_asyncio_transport
        if not transport:
            raise ValueError(f"{context} not supported with {transport=}")

    def _check_ssl_support(self) -> None:
        self._check_asyncio_transport("SSL/TLS")

    def __verify_ssl_context(self, ctx: _SSLContext) -> None:
        if ssl is None:
            raise RuntimeError("stdlib ssl module not available")
        if not isinstance(ctx, ssl.SSLContext):
            raise ValueError(f"Expected a ssl.SSLContext instance, got {ctx!r}")
