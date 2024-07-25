# Copyright 2021-2024, Francis Clairicia-Rose-Claire-Josephine
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
"""trio engine for easynetwork.api_async
"""

from __future__ import annotations

__all__ = ["TrioBackend"]

import functools
import math
import socket as _socket
from collections.abc import Awaitable, Callable, Coroutine, Mapping, Sequence
from typing import Any, NoReturn, ParamSpec, TypeVar, TypeVarTuple

from ...transports.abc import AsyncDatagramListener, AsyncDatagramTransport, AsyncListener, AsyncStreamTransport
from ..abc import AsyncBackend as AbstractAsyncBackend, CancelScope, ICondition, IEvent, ILock, TaskGroup, TaskInfo, ThreadsPortal

_P = ParamSpec("_P")
_T = TypeVar("_T")
_T_co = TypeVar("_T_co", covariant=True)
_T_PosArgs = TypeVarTuple("_T_PosArgs")


class TrioBackend(AbstractAsyncBackend):
    __slots__ = ("__trio",)

    def __init__(self) -> None:
        import trio

        self.__trio = trio

    def bootstrap(
        self,
        coro_func: Callable[[*_T_PosArgs], Coroutine[Any, Any, _T]],
        *args: *_T_PosArgs,
        runner_options: Mapping[str, Any] | None = None,
    ) -> _T:
        runner_options = runner_options or {}
        return self.__trio.run(coro_func, *args, **runner_options)

    async def coro_yield(self) -> None:
        await self.__trio.lowlevel.checkpoint()

    async def cancel_shielded_coro_yield(self) -> None:
        await self.__trio.lowlevel.cancel_shielded_checkpoint()

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
        raise AssertionError("Expected code to be unreachable")

    def create_task_group(self) -> TaskGroup:
        from .tasks import TaskGroup

        return TaskGroup()

    def get_current_task(self) -> TaskInfo:
        from .tasks import TaskUtils

        current_task = self.__trio.lowlevel.current_task()
        return TaskUtils.create_task_info(current_task)

    async def create_tcp_connection(
        self,
        host: str,
        port: int,
        *,
        local_address: tuple[str, int] | None = None,
        happy_eyeballs_delay: float | None = None,
    ) -> AsyncStreamTransport:
        raise NotImplementedError

    async def wrap_stream_socket(self, socket: _socket.socket) -> AsyncStreamTransport:
        raise NotImplementedError

    async def create_tcp_listeners(
        self,
        host: str | Sequence[str] | None,
        port: int,
        backlog: int,
        *,
        reuse_port: bool = False,
    ) -> Sequence[AsyncListener[AsyncStreamTransport]]:
        raise NotImplementedError

    async def create_udp_endpoint(
        self,
        remote_host: str,
        remote_port: int,
        *,
        local_address: tuple[str, int] | None = None,
        family: int = _socket.AF_UNSPEC,
    ) -> AsyncDatagramTransport:
        raise NotImplementedError

    async def wrap_connected_datagram_socket(self, socket: _socket.socket) -> AsyncDatagramTransport:
        raise NotImplementedError

    async def create_udp_listeners(
        self,
        host: str | Sequence[str] | None,
        port: int,
        *,
        reuse_port: bool = False,
    ) -> Sequence[AsyncDatagramListener[tuple[Any, ...]]]:
        raise NotImplementedError

    def create_lock(self) -> ILock:
        return self.__trio.Lock()

    def create_event(self) -> IEvent:
        return self.__trio.Event()

    def create_condition_var(self, lock: ILock | None = None) -> ICondition:
        if lock is not None:
            assert isinstance(lock, self.__trio.Lock)  # nosec assert_used

        return self.__trio.Condition(lock)

    async def run_in_thread(self, func: Callable[_P, _T], /, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        cb = functools.partial(func, *args, **kwargs)
        return await self.__trio.to_thread.run_sync(cb)

    def create_threads_portal(self) -> ThreadsPortal:
        from .threads import ThreadsPortal

        return ThreadsPortal()
