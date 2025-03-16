# Copyright 2021-2025, Francis Clairicia-Rose-Claire-Josephine
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
"""asyncio engine for easynetwork.api_async"""

from __future__ import annotations

__all__ = ["AsyncIOBackend"]

import contextvars
import functools
import math
import os
import socket as _socket
import sys
from collections.abc import Awaitable, Callable, Coroutine, Mapping, Sequence
from typing import Any, NoReturn, TypeVar, TypeVarTuple

from .... import _unix_utils, _utils
from ....constants import HAPPY_EYEBALLS_DELAY as _DEFAULT_HAPPY_EYEBALLS_DELAY
from ...transports.abc import AsyncDatagramListener, AsyncDatagramTransport, AsyncListener, AsyncStreamTransport
from ..abc import AsyncBackend as AbstractAsyncBackend, CancelScope, ICondition, IEvent, ILock, TaskGroup, TaskInfo, ThreadsPortal

_T = TypeVar("_T")
_T_co = TypeVar("_T_co", covariant=True)
_T_PosArgs = TypeVarTuple("_T_PosArgs")


class AsyncIOBackend(AbstractAsyncBackend):
    __slots__ = (
        "__asyncio",
        "__coro_yield",
        "__cancel_shielded_coro_yield",
        "__cancel_shielded_await",
        "__current_task",
        "__create_task_info",
        "__dns_resolver",
    )

    def __init__(self) -> None:
        import asyncio

        from .dns_resolver import AsyncIODNSResolver
        from .tasks import TaskUtils

        self.__asyncio = asyncio

        self.__coro_yield = TaskUtils.coro_yield
        self.__cancel_shielded_coro_yield = TaskUtils.cancel_shielded_coro_yield
        self.__cancel_shielded_await = TaskUtils.cancel_shielded_await
        self.__current_task = TaskUtils.current_asyncio_task
        self.__create_task_info = TaskUtils.create_task_info

        self.__dns_resolver = AsyncIODNSResolver()

    def __repr__(self) -> str:
        return f"<{type(self).__qualname__} object at {id(self):#x}>"

    def bootstrap(
        self,
        coro_func: Callable[[*_T_PosArgs], Coroutine[Any, Any, _T]],
        *args: *_T_PosArgs,
        runner_options: Mapping[str, Any] | None = None,
    ) -> _T:
        from sniffio import thread_local

        old_name, thread_local.name = thread_local.name, "asyncio"
        try:
            with self.__asyncio.Runner(**(runner_options or {})) as runner:
                return runner.run(coro_func(*args))
        finally:
            thread_local.name = old_name

    async def coro_yield(self) -> None:
        await self.__coro_yield()

    async def cancel_shielded_coro_yield(self) -> None:
        await self.__cancel_shielded_coro_yield()

    def get_cancelled_exc_class(self) -> type[BaseException]:
        return self.__asyncio.CancelledError

    async def ignore_cancellation(self, coroutine: Awaitable[_T_co]) -> _T_co:
        return await self.__cancel_shielded_await(coroutine)

    def open_cancel_scope(self, *, deadline: float = math.inf) -> CancelScope:
        from .tasks import CancelScope

        return CancelScope(deadline=deadline)

    def current_time(self) -> float:
        loop = self.__asyncio.get_running_loop()
        return loop.time()

    async def sleep(self, delay: float) -> None:
        await self.__asyncio.sleep(delay)

    async def sleep_forever(self) -> NoReturn:
        loop = self.__asyncio.get_running_loop()
        await loop.create_future()
        raise AssertionError("await an unused future cannot end in any other way than by cancellation")

    def create_task_group(self) -> TaskGroup:
        from .tasks import TaskGroup

        return TaskGroup()

    def get_current_task(self) -> TaskInfo:
        current_task = self.__current_task()
        return self.__create_task_info(current_task)

    async def getaddrinfo(
        self,
        host: bytes | str | None,
        port: bytes | str | int | None,
        family: int = 0,
        type: int = 0,
        proto: int = 0,
        flags: int = 0,
    ) -> Sequence[tuple[int, int, int, str, tuple[str, int] | tuple[str, int, int, int] | tuple[int, bytes]]]:
        loop = self.__asyncio.get_running_loop()

        return await loop.getaddrinfo(
            host,
            port,
            family=family,
            type=type,
            proto=proto,
            flags=flags,
        )

    async def getnameinfo(self, sockaddr: tuple[str, int] | tuple[str, int, int, int], flags: int = 0) -> tuple[str, str]:
        loop = self.__asyncio.get_running_loop()

        return await loop.getnameinfo(sockaddr, flags)

    async def create_tcp_connection(
        self,
        host: str,
        port: int,
        *,
        local_address: tuple[str, int] | None = None,
        happy_eyeballs_delay: float | None = None,
    ) -> AsyncStreamTransport:
        if happy_eyeballs_delay is None:
            happy_eyeballs_delay = _DEFAULT_HAPPY_EYEBALLS_DELAY

        socket = await self.__dns_resolver.create_stream_connection(
            self,
            host,
            port,
            local_address=local_address,
            happy_eyeballs_delay=happy_eyeballs_delay,
        )

        return await self.wrap_stream_socket(socket)

    async def create_unix_stream_connection(
        self,
        path: str | bytes,
        *,
        local_path: str | bytes | None = None,
    ) -> AsyncStreamTransport:
        from .stream.socket import AsyncioTransportStreamSocketAdapter, StreamReaderBufferedProtocol

        AF_UNIX: int = getattr(_socket, "AF_UNIX")
        loop = self.__asyncio.get_running_loop()

        socket = _socket.socket(AF_UNIX, _socket.SOCK_STREAM, 0)
        try:
            if local_path is not None:
                await loop.run_in_executor(None, self.__bind_unix_socket, socket, local_path)
            socket.setblocking(False)
            await loop.sock_connect(socket, path)
        except BaseException:
            socket.close()
            raise

        transport, protocol = await loop.create_unix_connection(
            _utils.make_callback(StreamReaderBufferedProtocol, loop=loop),
            sock=socket,
        )
        return AsyncioTransportStreamSocketAdapter(self, transport, protocol)

    async def wrap_stream_socket(self, socket: _socket.socket) -> AsyncStreamTransport:
        from .stream.socket import AsyncioTransportStreamSocketAdapter, StreamReaderBufferedProtocol

        socket.setblocking(False)
        loop = self.__asyncio.get_running_loop()
        if _unix_utils.is_unix_socket_family(socket.family):
            # Technically, loop.create_connection() would work for Unix sockets but it is currently supported
            # for backward compatibility. It is better to directly use the provided way instead.
            transport, protocol = await loop.create_unix_connection(
                _utils.make_callback(StreamReaderBufferedProtocol, loop=loop),
                sock=socket,
            )
        else:
            transport, protocol = await loop.create_connection(
                _utils.make_callback(StreamReaderBufferedProtocol, loop=loop),
                sock=socket,
            )
        return AsyncioTransportStreamSocketAdapter(self, transport, protocol)

    async def create_tcp_listeners(
        self,
        host: str | Sequence[str] | None,
        port: int,
        backlog: int,
        *,
        reuse_port: bool = False,
    ) -> Sequence[AsyncListener[AsyncStreamTransport]]:
        from .stream.listener import AcceptedSocketFactory, ListenerSocketAdapter

        reuse_address: bool = os.name not in ("nt", "cygwin") and sys.platform != "cygwin"
        hosts: Sequence[str | None] = _utils.validate_listener_hosts(host)

        del host

        infos: Sequence[tuple[int, int, int, str, tuple[Any, ...]]] = await self.__dns_resolver.resolve_listener_addresses(
            self,
            hosts,
            port,
            _socket.SOCK_STREAM,
        )

        sockets: list[_socket.socket] = _utils.open_listener_sockets_from_getaddrinfo_result(
            infos,
            reuse_address=reuse_address,
            reuse_port=reuse_port,
        )
        for sock in sockets:
            sock.listen(backlog)

        factory = AcceptedSocketFactory()
        listeners = [ListenerSocketAdapter(self, sock, factory, backlog=backlog) for sock in sockets]
        return listeners

    async def create_unix_stream_listener(
        self,
        path: str | bytes,
        backlog: int,
        *,
        mode: int | None = None,
    ) -> AsyncListener[AsyncStreamTransport]:
        from .stream.listener import AcceptedSocketFactory, ListenerSocketAdapter

        AF_UNIX: int = getattr(_socket, "AF_UNIX")
        loop = self.__asyncio.get_running_loop()

        socket = _socket.socket(AF_UNIX, _socket.SOCK_STREAM, 0)
        try:
            await loop.run_in_executor(None, self.__bind_unix_socket, socket, path)
            if mode is not None:
                await loop.run_in_executor(None, os.chmod, path, mode)
            socket.setblocking(False)
            socket.listen(backlog)
        except BaseException:
            socket.close()
            raise

        listener = ListenerSocketAdapter(self, socket, AcceptedSocketFactory(), backlog=backlog)
        return listener

    async def create_udp_endpoint(
        self,
        remote_host: str,
        remote_port: int,
        *,
        local_address: tuple[str, int] | None = None,
        family: int = _socket.AF_UNSPEC,
    ) -> AsyncDatagramTransport:
        socket = await self.__dns_resolver.create_datagram_connection(
            self,
            remote_host,
            remote_port,
            local_address=local_address,
            family=family,
        )
        return await self.wrap_connected_datagram_socket(socket)

    async def create_unix_datagram_endpoint(
        self,
        path: str | bytes,
        *,
        local_path: str | bytes | None = None,
    ) -> AsyncDatagramTransport:
        from .datagram.endpoint import create_datagram_endpoint
        from .datagram.socket import AsyncioTransportDatagramSocketAdapter

        AF_UNIX: int = getattr(_socket, "AF_UNIX")
        loop = self.__asyncio.get_running_loop()

        socket = _socket.socket(AF_UNIX, _socket.SOCK_DGRAM, 0)
        try:
            if local_path is not None:
                await loop.run_in_executor(None, self.__bind_unix_socket, socket, local_path)
            socket.setblocking(False)
            await loop.sock_connect(socket, path)
        except BaseException:
            socket.close()
            raise

        endpoint = await create_datagram_endpoint(sock=socket)
        return AsyncioTransportDatagramSocketAdapter(self, endpoint)

    async def wrap_connected_datagram_socket(self, socket: _socket.socket) -> AsyncDatagramTransport:
        from .datagram.endpoint import create_datagram_endpoint
        from .datagram.socket import AsyncioTransportDatagramSocketAdapter

        socket.setblocking(False)
        endpoint = await create_datagram_endpoint(sock=socket)
        return AsyncioTransportDatagramSocketAdapter(self, endpoint)

    async def create_udp_listeners(
        self,
        host: str | Sequence[str] | None,
        port: int,
        *,
        reuse_port: bool = False,
    ) -> Sequence[AsyncDatagramListener[tuple[Any, ...]]]:
        from .datagram.listener import DatagramListenerProtocol, DatagramListenerSocketAdapter

        loop = self.__asyncio.get_running_loop()

        hosts: Sequence[str | None] = _utils.validate_listener_hosts(host)

        del host

        infos: Sequence[tuple[int, int, int, str, tuple[Any, ...]]] = await self.__dns_resolver.resolve_listener_addresses(
            self,
            hosts,
            port,
            _socket.SOCK_DGRAM,
        )

        sockets: list[_socket.socket] = _utils.open_listener_sockets_from_getaddrinfo_result(
            infos,
            reuse_address=False,
            reuse_port=reuse_port,
        )
        protocol_factory = _utils.make_callback(DatagramListenerProtocol, loop=loop)

        listeners = [await loop.create_datagram_endpoint(protocol_factory, sock=sock) for sock in sockets]
        return [DatagramListenerSocketAdapter(self, transport, protocol) for transport, protocol in listeners]

    async def create_unix_datagram_listener(
        self,
        path: str | bytes,
        *,
        mode: int | None = None,
    ) -> AsyncDatagramListener[str | bytes]:
        from .datagram.listener import DatagramListenerProtocol, DatagramListenerSocketAdapter

        loop = self.__asyncio.get_running_loop()

        AF_UNIX: int = getattr(_socket, "AF_UNIX")
        socket = _socket.socket(AF_UNIX, _socket.SOCK_DGRAM, 0)
        try:
            await loop.run_in_executor(None, self.__bind_unix_socket, socket, path)
            if mode is not None:
                await loop.run_in_executor(None, os.chmod, path, mode)
            socket.setblocking(False)
        except BaseException:
            socket.close()
            raise

        transport, protocol = await loop.create_datagram_endpoint(
            _utils.make_callback(DatagramListenerProtocol, loop=loop),
            sock=socket,
        )
        listener = DatagramListenerSocketAdapter(self, transport, protocol)
        return listener

    def create_lock(self) -> ILock:
        return self.__asyncio.Lock()

    def create_fair_lock(self) -> ILock:
        # For now, asyncio.Lock is already a fair (and fast) lock.
        return self.__asyncio.Lock()

    def create_event(self) -> IEvent:
        return self.__asyncio.Event()

    def create_condition_var(self, lock: ILock | None = None) -> ICondition:
        match lock:
            case None:
                return self.__asyncio.Condition()
            case self.__asyncio.Lock():
                return self.__asyncio.Condition(lock)
            case _:
                raise TypeError("lock must be a asyncio.Lock")

    async def run_in_thread(
        self,
        func: Callable[[*_T_PosArgs], _T],
        /,
        *args: *_T_PosArgs,
        abandon_on_cancel: bool = False,
    ) -> _T:
        import sniffio

        loop = self.__asyncio.get_running_loop()
        ctx = contextvars.copy_context()

        ctx.run(sniffio.current_async_library_cvar.set, None)

        cb = functools.partial(ctx.run, func, *args)
        if abandon_on_cancel:
            return await loop.run_in_executor(None, cb)
        else:
            return await self.__cancel_shielded_await(loop.run_in_executor(None, cb))

    def create_threads_portal(self) -> ThreadsPortal:
        from .threads import ThreadsPortal

        return ThreadsPortal()

    def __bind_unix_socket(self, socket: _socket.socket, local_path: str | bytes) -> None:
        try:
            socket.bind(local_path)
        except OSError as exc:
            raise _utils.convert_socket_bind_error(exc, local_path) from None
