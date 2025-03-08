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
"""trio engine for easynetwork.api_async"""

from __future__ import annotations

__all__ = ["TrioBackend"]

import math
import os
import socket as _socket
import sys
from collections.abc import Awaitable, Callable, Coroutine, Mapping, Sequence
from typing import Any, NoReturn, TypeVar, TypeVarTuple

from .... import _utils
from ....constants import HAPPY_EYEBALLS_DELAY as _DEFAULT_HAPPY_EYEBALLS_DELAY
from ...transports.abc import AsyncDatagramListener, AsyncDatagramTransport, AsyncListener, AsyncStreamTransport
from ..abc import AsyncBackend as AbstractAsyncBackend, CancelScope, ICondition, IEvent, ILock, TaskGroup, TaskInfo, ThreadsPortal

_T = TypeVar("_T")
_T_co = TypeVar("_T_co", covariant=True)
_T_PosArgs = TypeVarTuple("_T_PosArgs")


class TrioBackend(AbstractAsyncBackend):
    __slots__ = (
        "__trio",
        "__trio_utils",
        "__trio_lowlevel",
        "__create_task_info",
        "__dns_resolver",
    )

    def __init__(self) -> None:
        try:
            import trio
        except ModuleNotFoundError as exc:
            raise _utils.missing_extra_deps("trio") from exc

        from . import _trio_utils
        from .dns_resolver import TrioDNSResolver
        from .tasks import TaskUtils

        self.__trio = trio
        self.__trio_utils = _trio_utils
        self.__trio_lowlevel = trio.lowlevel

        self.__create_task_info = TaskUtils.create_task_info

        self.__dns_resolver = TrioDNSResolver()

    def __repr__(self) -> str:
        return f"<{type(self).__qualname__} object at {id(self):#x}>"

    def bootstrap(
        self,
        coro_func: Callable[[*_T_PosArgs], Coroutine[Any, Any, _T]],
        *args: *_T_PosArgs,
        runner_options: Mapping[str, Any] | None = None,
    ) -> _T:
        runner_options = runner_options or {}
        return self.__trio.run(coro_func, *args, **runner_options)

    async def coro_yield(self) -> None:
        await self.__trio_lowlevel.checkpoint()

    async def cancel_shielded_coro_yield(self) -> None:
        await self.__trio_lowlevel.cancel_shielded_checkpoint()

    def get_cancelled_exc_class(self) -> type[BaseException]:
        return self.__trio.Cancelled

    async def ignore_cancellation(self, coroutine: Awaitable[_T_co]) -> _T_co:
        with self.__trio.CancelScope(shield=True):
            try:
                return await coroutine
            finally:
                del coroutine
        raise AssertionError("Expected code to be unreachable")

    def open_cancel_scope(self, *, deadline: float = math.inf) -> CancelScope:
        from .tasks import CancelScope

        return CancelScope(deadline=deadline)

    def current_time(self) -> float:
        return self.__trio.current_time()

    async def sleep(self, delay: float) -> None:
        await self.__trio.sleep(delay)

    async def sleep_forever(self) -> NoReturn:
        await self.__trio.sleep_forever()

    def create_task_group(self) -> TaskGroup:
        from .tasks import TaskGroup

        return TaskGroup()

    def get_current_task(self) -> TaskInfo:
        current_task = self.__trio_lowlevel.current_task()
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
        return await self.__trio.socket.getaddrinfo(
            host,
            port,
            family=family,
            type=type,
            proto=proto,
            flags=flags,
        )

    async def getnameinfo(self, sockaddr: tuple[str, int] | tuple[str, int, int, int], flags: int = 0) -> tuple[str, str]:
        return await self.__trio.socket.getnameinfo(sockaddr, flags)

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
        from ._trio_utils import connect_sock_to_resolved_address

        AF_UNIX: int = getattr(_socket, "AF_UNIX")

        socket = _socket.socket(AF_UNIX, _socket.SOCK_STREAM, 0)
        try:
            if local_path is not None:
                await self.__trio.to_thread.run_sync(self.__bind_unix_socket, socket, local_path, abandon_on_cancel=True)
            socket.setblocking(False)
            await connect_sock_to_resolved_address(socket, path)
        except BaseException:
            socket.close()
            raise

        return await self.wrap_stream_socket(socket)

    async def wrap_stream_socket(self, socket: _socket.socket) -> AsyncStreamTransport:
        from .stream.socket import TrioStreamSocketAdapter

        _utils.check_socket_no_ssl(socket)
        trio_socket = self.__trio.socket.from_stdlib_socket(socket)
        trio_stream = self.__trio.SocketStream(trio_socket)

        return TrioStreamSocketAdapter(self, trio_stream)

    async def create_tcp_listeners(
        self,
        host: str | Sequence[str] | None,
        port: int,
        backlog: int,
        *,
        reuse_port: bool = False,
    ) -> Sequence[AsyncListener[AsyncStreamTransport]]:
        from .stream.listener import TrioListenerSocketAdapter

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

        listeners = [
            TrioListenerSocketAdapter(self, self.__trio.SocketListener(sock))
            for sock in map(self.__trio.socket.from_stdlib_socket, sockets)
        ]
        return listeners

    async def create_unix_stream_listener(
        self,
        path: str | bytes,
        backlog: int,
        *,
        mode: int | None = None,
    ) -> AsyncListener[AsyncStreamTransport]:
        from .stream.listener import TrioListenerSocketAdapter

        AF_UNIX: int = getattr(_socket, "AF_UNIX")

        socket = _socket.socket(AF_UNIX, _socket.SOCK_STREAM, 0)
        try:
            await self.__trio.to_thread.run_sync(self.__bind_unix_socket, socket, path, abandon_on_cancel=True)
            if mode is not None:
                await self.__trio.to_thread.run_sync(os.chmod, path, mode, abandon_on_cancel=True)
            socket.setblocking(False)
            socket.listen(backlog)
        except BaseException:
            socket.close()
            raise

        trio_socket = self.__trio.socket.from_stdlib_socket(socket)
        listener = TrioListenerSocketAdapter(self, self.__trio.SocketListener(trio_socket))
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
        from ._trio_utils import connect_sock_to_resolved_address

        AF_UNIX: int = getattr(_socket, "AF_UNIX")

        socket = _socket.socket(AF_UNIX, _socket.SOCK_DGRAM, 0)
        try:
            if local_path is not None:
                await self.__trio.to_thread.run_sync(self.__bind_unix_socket, socket, local_path, abandon_on_cancel=True)
            socket.setblocking(False)
            await connect_sock_to_resolved_address(socket, path)
        except BaseException:
            socket.close()
            raise

        return await self.wrap_connected_datagram_socket(socket)

    async def wrap_connected_datagram_socket(self, socket: _socket.socket) -> AsyncDatagramTransport:
        from .datagram.socket import TrioDatagramSocketAdapter

        _utils.check_socket_no_ssl(socket)
        trio_socket = self.__trio.socket.from_stdlib_socket(socket)

        return TrioDatagramSocketAdapter(self, trio_socket)

    async def create_udp_listeners(
        self,
        host: str | Sequence[str] | None,
        port: int,
        *,
        reuse_port: bool = False,
    ) -> Sequence[AsyncDatagramListener[tuple[Any, ...]]]:
        from .datagram.listener import TrioDatagramListenerSocketAdapter

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

        listeners = [TrioDatagramListenerSocketAdapter(self, sock) for sock in sockets]
        return listeners

    async def create_unix_datagram_listener(
        self,
        path: str | bytes,
        *,
        mode: int | None = None,
    ) -> AsyncDatagramListener[str | bytes]:
        from .datagram.listener import TrioDatagramListenerSocketAdapter

        AF_UNIX: int = getattr(_socket, "AF_UNIX")

        socket = _socket.socket(AF_UNIX, _socket.SOCK_DGRAM, 0)
        try:
            await self.__trio.to_thread.run_sync(self.__bind_unix_socket, socket, path, abandon_on_cancel=True)
            if mode is not None:
                await self.__trio.to_thread.run_sync(os.chmod, path, mode, abandon_on_cancel=True)
            socket.setblocking(False)
        except BaseException:
            socket.close()
            raise

        listener = TrioDatagramListenerSocketAdapter(self, socket)
        return listener

    def create_lock(self) -> ILock:
        return self.__trio.Lock()

    def create_fair_lock(self) -> ILock:
        return self.__trio_utils.FastFIFOLock()

    def create_event(self) -> IEvent:
        return self.__trio.Event()

    def create_condition_var(self, lock: ILock | None = None) -> ICondition:
        match lock:
            case None:
                return self.__trio.Condition()
            case self.__trio.Lock():
                return self.__trio.Condition(lock)
            case _:
                raise TypeError("lock must be a trio.Lock")

    async def run_in_thread(
        self,
        func: Callable[[*_T_PosArgs], _T],
        /,
        *args: *_T_PosArgs,
        abandon_on_cancel: bool = False,
    ) -> _T:
        return await self.__trio.to_thread.run_sync(func, *args, abandon_on_cancel=abandon_on_cancel)

    def create_threads_portal(self) -> ThreadsPortal:
        from .threads import ThreadsPortal

        return ThreadsPortal()

    def __bind_unix_socket(self, socket: _socket.socket, local_path: str | bytes) -> None:
        try:
            socket.bind(local_path)
        except OSError as exc:
            raise _utils.convert_socket_bind_error(exc, local_path) from None
