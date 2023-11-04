# Copyright 2021-2023, Francis Clairicia-Rose-Claire-Josephine
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
#
"""asyncio engine for easynetwork.api_async
"""

from __future__ import annotations

__all__ = ["AsyncIOBackend"]

import asyncio
import asyncio.base_events
import contextvars
import functools
import math
import os
import socket as _socket
import sys
from collections.abc import Callable, Coroutine, Mapping, Sequence
from contextlib import closing
from typing import TYPE_CHECKING, Any, NoReturn, ParamSpec, TypeVar

try:
    import ssl as _ssl
except ImportError:  # pragma: no cover
    ssl = None
else:
    ssl = _ssl
    del _ssl

from ..api_async.backend.abc import AsyncBackend as AbstractAsyncBackend
from ..api_async.backend.sniffio import current_async_library_cvar as _sniffio_current_async_library_cvar
from ._asyncio_utils import create_connection, open_listener_sockets_from_getaddrinfo_result, resolve_local_addresses
from .datagram.endpoint import create_datagram_endpoint
from .datagram.listener import AsyncioTransportDatagramListenerSocketAdapter, RawDatagramListenerSocketAdapter
from .datagram.socket import AsyncioTransportDatagramSocketAdapter, RawDatagramSocketAdapter
from .stream.listener import AcceptedSocketFactory, AcceptedSSLSocketFactory, ListenerSocketAdapter
from .stream.socket import AsyncioTransportStreamSocketAdapter, RawStreamSocketAdapter
from .tasks import CancelScope, TaskGroup, TaskUtils
from .threads import ThreadsPortal

if TYPE_CHECKING:
    import concurrent.futures
    from ssl import SSLContext as _SSLContext

    from ..api_async.backend.abc import ILock

_P = ParamSpec("_P")
_T = TypeVar("_T")
_T_co = TypeVar("_T_co", covariant=True)


class AsyncIOBackend(AbstractAsyncBackend):
    __slots__ = ("__use_asyncio_transport",)

    def __init__(self, *, transport: bool = True) -> None:
        self.__use_asyncio_transport: bool = bool(transport)

    def bootstrap(
        self,
        coro_func: Callable[..., Coroutine[Any, Any, _T]],
        *args: Any,
        runner_options: Mapping[str, Any] | None = None,
    ) -> _T:
        # Avoid ResourceWarning by always closing the coroutine
        with asyncio.Runner(**(runner_options or {})) as runner, closing(coro_func(*args)) as coro:
            return runner.run(coro)

    async def coro_yield(self) -> None:
        await asyncio.sleep(0)

    async def cancel_shielded_coro_yield(self) -> None:
        await TaskUtils.cancel_shielded_coro_yield()

    def get_cancelled_exc_class(self) -> type[BaseException]:
        return asyncio.CancelledError

    async def ignore_cancellation(self, coroutine: Coroutine[Any, Any, _T_co]) -> _T_co:
        if not asyncio.iscoroutine(coroutine):
            raise TypeError("Expected a coroutine object")
        return await TaskUtils.cancel_shielded_await_task(asyncio.create_task(coroutine))

    def open_cancel_scope(self, *, deadline: float = math.inf) -> CancelScope:
        return CancelScope(deadline=deadline)

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
            )
        else:
            reader, writer = await asyncio.open_connection(
                host,
                port,
                local_addr=local_address,
                happy_eyeballs_delay=happy_eyeballs_delay,
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
            )
        return AsyncioTransportStreamSocketAdapter(reader, writer)

    @staticmethod
    def _default_happy_eyeballs_delay(happy_eyeballs_delay: float | None) -> float | None:
        if happy_eyeballs_delay is None:
            running_loop = asyncio.get_running_loop()
            if isinstance(running_loop, asyncio.base_events.BaseEventLoop):  # Base class of standard implementation
                happy_eyeballs_delay = 0.25  # Recommended value by the RFC 6555
        return happy_eyeballs_delay

    async def wrap_stream_socket(
        self,
        socket: _socket.socket,
    ) -> AsyncioTransportStreamSocketAdapter | RawStreamSocketAdapter:
        socket.setblocking(False)

        if not self.__use_asyncio_transport:
            return RawStreamSocketAdapter(socket, asyncio.get_running_loop())

        reader, writer = await asyncio.open_connection(sock=socket)
        return AsyncioTransportStreamSocketAdapter(reader, writer)

    async def wrap_ssl_over_stream_socket_client_side(
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

        socket.setblocking(False)

        reader, writer = await asyncio.open_connection(
            sock=socket,
            ssl=ssl_context,
            server_hostname=server_hostname,
            ssl_handshake_timeout=float(ssl_handshake_timeout),
            ssl_shutdown_timeout=float(ssl_shutdown_timeout),
        )
        return AsyncioTransportStreamSocketAdapter(reader, writer)

    async def create_tcp_listeners(
        self,
        host: str | Sequence[str] | None,
        port: int,
        backlog: int,
        *,
        reuse_port: bool = False,
    ) -> Sequence[ListenerSocketAdapter[AsyncioTransportStreamSocketAdapter | RawStreamSocketAdapter]]:
        sockets = await self._create_tcp_socket_listeners(host, port, backlog, reuse_port=reuse_port)

        loop = asyncio.get_running_loop()
        factory = AcceptedSocketFactory(use_asyncio_transport=self.__use_asyncio_transport)
        return [ListenerSocketAdapter(sock, loop, factory) for sock in sockets]

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
    ) -> Sequence[ListenerSocketAdapter[AsyncioTransportStreamSocketAdapter]]:
        self._check_ssl_support()
        self.__verify_ssl_context(ssl_context)

        sockets = await self._create_tcp_socket_listeners(host, port, backlog, reuse_port=reuse_port)

        loop = asyncio.get_running_loop()
        factory = AcceptedSSLSocketFactory(
            ssl_context=ssl_context,
            ssl_handshake_timeout=float(ssl_handshake_timeout),
            ssl_shutdown_timeout=float(ssl_shutdown_timeout),
        )
        return [ListenerSocketAdapter(sock, loop, factory) for sock in sockets]

    async def _create_tcp_socket_listeners(
        self,
        host: str | Sequence[str] | None,
        port: int,
        backlog: int,
        *,
        reuse_port: bool,
    ) -> Sequence[_socket.socket]:
        if not isinstance(backlog, int):
            raise TypeError("backlog: Expected an integer")
        loop = asyncio.get_running_loop()

        reuse_address: bool = os.name not in ("nt", "cygwin") and sys.platform != "cygwin"
        hosts: Sequence[str | None]
        if host == "" or host is None:
            hosts = [None]
        elif isinstance(host, str):
            hosts = [host]
        else:
            hosts = host

        del host

        infos: Sequence[tuple[int, int, int, str, tuple[Any, ...]]] = await resolve_local_addresses(
            hosts,
            port,
            _socket.SOCK_STREAM,
            loop,
        )

        sockets: list[_socket.socket] = open_listener_sockets_from_getaddrinfo_result(
            infos,
            backlog=backlog,
            reuse_address=reuse_address,
            reuse_port=reuse_port,
        )

        return sockets

    async def create_udp_endpoint(
        self,
        remote_host: str,
        remote_port: int,
        *,
        local_address: tuple[str, int] | None = None,
    ) -> AsyncioTransportDatagramSocketAdapter | RawDatagramSocketAdapter:
        loop = asyncio.get_running_loop()
        socket = await create_connection(
            remote_host,
            remote_port,
            loop,
            local_address=local_address,
            socktype=_socket.SOCK_DGRAM,
        )
        return await self.wrap_connected_datagram_socket(socket)

    async def wrap_connected_datagram_socket(
        self,
        socket: _socket.socket,
    ) -> AsyncioTransportDatagramSocketAdapter | RawDatagramSocketAdapter:
        socket.setblocking(False)

        if not self.__use_asyncio_transport:
            return RawDatagramSocketAdapter(socket, asyncio.get_running_loop())

        endpoint = await create_datagram_endpoint(sock=socket)
        return AsyncioTransportDatagramSocketAdapter(endpoint)

    async def create_udp_listeners(
        self,
        host: str | Sequence[str] | None,
        port: int,
        *,
        reuse_port: bool = False,
    ) -> Sequence[AsyncioTransportDatagramListenerSocketAdapter] | Sequence[RawDatagramListenerSocketAdapter]:
        loop = asyncio.get_running_loop()

        hosts: Sequence[str | None]
        if host == "" or host is None:
            hosts = [None]
        elif isinstance(host, str):
            hosts = [host]
        else:
            hosts = host

        del host

        infos: Sequence[tuple[int, int, int, str, tuple[Any, ...]]] = await resolve_local_addresses(
            hosts,
            port,
            _socket.SOCK_DGRAM,
            loop,
        )

        sockets: list[_socket.socket] = open_listener_sockets_from_getaddrinfo_result(
            infos,
            backlog=None,
            reuse_address=False,
            reuse_port=reuse_port,
        )

        if not self.__use_asyncio_transport:
            return [RawDatagramListenerSocketAdapter(sock, loop) for sock in sockets]
        return [AsyncioTransportDatagramListenerSocketAdapter(await create_datagram_endpoint(sock=sock)) for sock in sockets]

    def create_lock(self) -> asyncio.Lock:
        return asyncio.Lock()

    def create_event(self) -> asyncio.Event:
        return asyncio.Event()

    def create_condition_var(self, lock: ILock | None = None) -> asyncio.Condition:
        if lock is not None:
            assert isinstance(lock, asyncio.Lock)  # nosec assert_used

        return asyncio.Condition(lock)

    async def run_in_thread(self, func: Callable[_P, _T], /, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        loop = asyncio.get_running_loop()
        ctx = contextvars.copy_context()

        if _sniffio_current_async_library_cvar is not None:
            ctx.run(_sniffio_current_async_library_cvar.set, None)

        future = loop.run_in_executor(None, functools.partial(ctx.run, func, *args, **kwargs))
        try:
            await TaskUtils.cancel_shielded_wait_asyncio_futures({future})
            return future.result()
        finally:
            del future

    def create_threads_portal(self) -> ThreadsPortal:
        return ThreadsPortal()

    async def wait_future(self, future: concurrent.futures.Future[_T_co]) -> _T_co:
        if not future.done():
            future_wrapper = asyncio.wrap_future(future)
            try:
                # If future.cancel() failed, that means future.set_running_or_notify_cancel() has been called
                # and set future in RUNNING state.
                # This future cannot be cancelled anymore, therefore it must be awaited.
                await TaskUtils.cancel_shielded_wait_asyncio_futures({future_wrapper}, abort_func=future.cancel)

                # Unwrap "future_wrapper" to prevent reports about unhandled exceptions.
                if not future_wrapper.cancelled():
                    del future
                    return future_wrapper.result()
            finally:
                del future_wrapper

        try:
            if future.cancelled():
                # Task cancellation prevails over future cancellation
                await asyncio.sleep(0)
            return future.result(timeout=0)
        finally:
            del future

    def using_asyncio_transport(self) -> bool:
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
