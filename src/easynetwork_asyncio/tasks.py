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

__all__ = ["Task", "TaskGroup", "TimeoutHandle", "timeout", "timeout_at"]

import asyncio
import contextvars
import math
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any, ParamSpec, Self, TypeVar, final

from easynetwork.api_async.backend.abc import AbstractTask, AbstractTaskGroup, AbstractTimeoutHandle

if TYPE_CHECKING:
    from types import TracebackType


_P = ParamSpec("_P")
_T = TypeVar("_T")
_T_co = TypeVar("_T_co", covariant=True)


@final
class Task(AbstractTask[_T_co]):
    __slots__ = ("__t", "__h")

    def __init__(self, task: asyncio.Task[_T_co]) -> None:
        self.__t: asyncio.Task[_T_co] = task
        self.__h: int | None = None

    def __hash__(self) -> int:
        if (h := self.__h) is None:
            self.__h = h = hash((Task, self.__t, 0xFF))
        return h

    def __eq__(self, other: object, /) -> bool:
        if not isinstance(other, Task):
            return NotImplemented
        return self.__t == other.__t

    def done(self) -> bool:
        return self.__t.done()

    def cancel(self) -> bool:
        return self.__t.cancel()

    def cancelled(self) -> bool:
        return self.__t.cancelled()

    async def wait(self) -> None:
        if self.__t.done():
            return
        await asyncio.wait({self.__t})

    async def join(self) -> _T_co:
        # If the caller cancels the join() task, it should not stop the inner task
        # e.g. when awaiting from an another task than the one which creates the TaskGroup,
        #      you want to stop joining the sub-task, not accidentally cancel it.
        # It is primarily to avoid error prone code where tasks were not explicitly cancelled using task.cancel()
        try:
            return await asyncio.shield(self.__t)
        finally:
            del self  # This is needed to avoid circular reference with raised exception


@final
class TaskGroup(AbstractTaskGroup):
    __slots__ = ("__asyncio_tg",)

    def __init__(self) -> None:
        super().__init__()
        self.__asyncio_tg: asyncio.TaskGroup = asyncio.TaskGroup()

    async def __aenter__(self) -> Self:
        asyncio_tg: asyncio.TaskGroup = self.__asyncio_tg
        await type(asyncio_tg).__aenter__(asyncio_tg)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        asyncio_tg: asyncio.TaskGroup = self.__asyncio_tg
        try:
            await type(asyncio_tg).__aexit__(asyncio_tg, exc_type, exc_val, exc_tb)
        finally:
            del exc_val, exc_tb, self

    def start_soon(
        self,
        __coro_func: Callable[_P, Coroutine[Any, Any, _T]],
        /,
        *args: _P.args,
        **kwargs: _P.kwargs,
    ) -> AbstractTask[_T]:
        return Task(self.__asyncio_tg.create_task(__coro_func(*args, **kwargs)))

    def start_soon_with_context(
        self,
        context: contextvars.Context,
        coro_func: Callable[_P, Coroutine[Any, Any, _T]],
        /,
        *args: _P.args,
        **kwargs: _P.kwargs,
    ) -> AbstractTask[_T]:
        assert context is not None
        return Task(self.__asyncio_tg.create_task(coro_func(*args, **kwargs), context=context))


@final
class TimeoutHandle(AbstractTimeoutHandle):
    __slots__ = ("__handle",)

    def __init__(self, handle: asyncio.Timeout) -> None:
        super().__init__()
        self.__handle: asyncio.Timeout = handle

    async def __aenter__(self) -> Self:
        handle: asyncio.Timeout = self.__handle
        await type(handle).__aenter__(handle)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        handle: asyncio.Timeout = self.__handle
        try:
            return await type(handle).__aexit__(handle, exc_type, exc_val, exc_tb)
        finally:
            del exc_val, exc_tb, self

    def when(self) -> float:
        deadline: float | None = self.__handle.when()
        return deadline if deadline is not None else math.inf

    def reschedule(self, when: float) -> None:
        assert when is not None
        return self.__handle.reschedule(when if when != math.inf else None)

    def expired(self) -> bool:
        return self.__handle.expired()


def timeout(delay: float) -> TimeoutHandle:
    assert delay is not None
    return TimeoutHandle(asyncio.timeout(delay if delay != math.inf else None))


def timeout_at(deadline: float) -> TimeoutHandle:
    assert deadline is not None
    return TimeoutHandle(asyncio.timeout_at(deadline if deadline != math.inf else None))
