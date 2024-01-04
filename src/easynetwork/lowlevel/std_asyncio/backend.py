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
from collections.abc import Awaitable, Callable, Coroutine, Mapping, Sequence
from typing import TYPE_CHECKING, Any, NoReturn, ParamSpec, TypeVar

try:
    import ssl as _ssl
except ImportError:  # pragma: no cover
    ssl = None
else:
    ssl = _ssl
    del _ssl

from ..api_async.backend import _sniffio_helpers
from ..api_async.backend.abc import AsyncBackend as AbstractAsyncBackend, TaskInfo
from ..constants import HAPPY_EYEBALLS_DELAY as _DEFAULT_HAPPY_EYEBALLS_DELAY
from ._asyncio_utils import (
    create_connection,
    create_datagram_connection,
    open_listener_sockets_from_getaddrinfo_result,
    resolve_local_addresses,
)
from .datagram.endpoint import create_datagram_endpoint
from .datagram.listener import DatagramListenerSocketAdapter
from .datagram.socket import AsyncioTransportDatagramSocketAdapter, RawDatagramSocketAdapter
from .stream.listener import AcceptedSocketFactory, AcceptedSSLSocketFactory, ListenerSocketAdapter
from .stream.socket import AsyncioTransportStreamSocketAdapter, RawStreamSocketAdapter
from .tasks import CancelScope, TaskGroup, TaskUtils
from .threads import ThreadsPortal

if TYPE_CHECKING:
    from ssl import SSLContext as _SSLContext

    from ..api_async.backend.abc import ILock

_P = ParamSpec("_P")
_T = TypeVar("_T")
_T_co = TypeVar("_T_co", covariant=True)


class AsyncIOBackend(AbstractAsyncBackend):
    __slots__ = ()

    def bootstrap(
        self,
        coro_func: Callable[..., Coroutine[Any, Any, _T]],
        *args: Any,
        runner_options: Mapping[str, Any] | None = None,
    ) -> _T:
        async def bootstrap_task() -> _T:
            TaskUtils.current_asyncio_task().set_name(TaskUtils.compute_task_name_from_func(coro_func))
            return await TaskUtils.ensure_coroutine(coro_func, args)

        with asyncio.Runner(**(runner_options or {})) as runner:
            return runner.run(bootstrap_task())

    async def coro_yield(self) -> None:
        await TaskUtils.coro_yield()

    async def cancel_shielded_coro_yield(self) -> None:
        await TaskUtils.cancel_shielded_coro_yield()

    def get_cancelled_exc_class(self) -> type[BaseException]:
        return asyncio.CancelledError

    async def ignore_cancellation(self, coroutine: Awaitable[_T_co]) -> _T_co:
        return await TaskUtils.cancel_shielded_await(coroutine)

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

    def get_current_task(self) -> TaskInfo:
        current_task = TaskUtils.current_asyncio_task()
        return TaskUtils.create_task_info(current_task)

    async def create_tcp_connection(
        self,
        host: str,
        port: int,
        *,
        local_address: tuple[str, int] | None = None,
        happy_eyeballs_delay: float | None = None,
    ) -> AsyncioTransportStreamSocketAdapter | RawStreamSocketAdapter:
        if happy_eyeballs_delay is None:
            happy_eyeballs_delay = _DEFAULT_HAPPY_EYEBALLS_DELAY

        loop = asyncio.get_running_loop()
        socket = await create_connection(
            host,
            port,
            loop,
            local_address=local_address,
            happy_eyeballs_delay=happy_eyeballs_delay,
        )

        return await self.wrap_stream_socket(socket)

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
        self.__verify_ssl_context(ssl_context)

        if happy_eyeballs_delay is None:
            happy_eyeballs_delay = _DEFAULT_HAPPY_EYEBALLS_DELAY

        if server_hostname is None:
            server_hostname = host

        loop = asyncio.get_running_loop()
        socket = await create_connection(
            host,
            port,
            loop,
            local_address=local_address,
            happy_eyeballs_delay=happy_eyeballs_delay,
        )

        return await self.wrap_ssl_over_stream_socket_client_side(
            socket,
            ssl_context=ssl_context,
            server_hostname=server_hostname,
            ssl_handshake_timeout=ssl_handshake_timeout,
            ssl_shutdown_timeout=ssl_shutdown_timeout,
        )

    async def wrap_stream_socket(
        self,
        socket: _socket.socket,
    ) -> AsyncioTransportStreamSocketAdapter | RawStreamSocketAdapter:
        socket.setblocking(False)

        if not self.using_asyncio_transports():
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
    ) -> Sequence[ListenerSocketAdapter[AsyncioTransportStreamSocketAdapter]]:
        sockets = await self._create_tcp_socket_listeners(host, port, backlog, reuse_port=reuse_port)

        loop = asyncio.get_running_loop()
        factory = AcceptedSocketFactory()
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
        family: int = _socket.AF_UNSPEC,
    ) -> AsyncioTransportDatagramSocketAdapter | RawDatagramSocketAdapter:
        loop = asyncio.get_running_loop()
        socket = await create_datagram_connection(
            remote_host,
            remote_port,
            loop,
            local_address=local_address,
            family=family,
        )
        return await self.wrap_connected_datagram_socket(socket)

    async def wrap_connected_datagram_socket(
        self,
        socket: _socket.socket,
    ) -> AsyncioTransportDatagramSocketAdapter | RawDatagramSocketAdapter:
        socket.setblocking(False)

        if not self.using_asyncio_transports():
            return RawDatagramSocketAdapter(socket, asyncio.get_running_loop())

        endpoint = await create_datagram_endpoint(sock=socket)
        return AsyncioTransportDatagramSocketAdapter(endpoint)

    async def create_udp_listeners(
        self,
        host: str | Sequence[str] | None,
        port: int,
        *,
        reuse_port: bool = False,
    ) -> Sequence[DatagramListenerSocketAdapter]:
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

        return [DatagramListenerSocketAdapter(await create_datagram_endpoint(sock=sock)) for sock in sockets]

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

        _sniffio_helpers.setup_sniffio_contextvar(ctx, None)

        future = loop.run_in_executor(None, functools.partial(ctx.run, func, *args, **kwargs))
        try:
            return await TaskUtils.cancel_shielded_await_future(future)
        finally:
            del future

    def create_threads_portal(self) -> ThreadsPortal:
        return ThreadsPortal()

    @classmethod
    def using_asyncio_transports(cls) -> bool:
        return os.environ.get("EASYNETWORK_HINT_FORCE_USE_ASYNCIO_TRANSPORTS", "") == "1"

    def __verify_ssl_context(self, ctx: _SSLContext) -> None:
        if ssl is None:
            raise RuntimeError("stdlib ssl module not available")
        if not isinstance(ctx, ssl.SSLContext):
            raise ValueError(f"Expected a ssl.SSLContext instance, got {ctx!r}")
