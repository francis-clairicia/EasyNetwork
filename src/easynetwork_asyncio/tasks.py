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
from collections import deque
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any, ParamSpec, Self, TypeVar, final
from weakref import WeakKeyDictionary

from easynetwork.api_async.backend.abc import AbstractSystemTask, AbstractTask, AbstractTaskGroup, AbstractTimeoutHandle

if TYPE_CHECKING:
    from types import TracebackType


_P = ParamSpec("_P")
_T = TypeVar("_T")
_T_co = TypeVar("_T_co", covariant=True)


class Task(AbstractTask[_T_co]):
    __slots__ = ("__t", "__h")

    def __init__(self, task: asyncio.Task[_T_co]) -> None:
        self.__t: asyncio.Task[_T_co] = task
        self.__h: int | None = None

    def __hash__(self) -> int:
        if (h := self.__h) is None:
            self.__h = h = hash((self.__class__, self.__t, 0xFF))
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
        task = self.__t
        try:
            if task.done():
                return
            await asyncio.wait({task})
        finally:
            del task, self  # This is needed to avoid circular reference with raised exception

    async def join(self) -> _T_co:
        # If the caller cancels the join() task, it should not stop the inner task
        # e.g. when awaiting from an another task than the one which creates the TaskGroup,
        #      you want to stop joining the sub-task, not accidentally cancel it.
        # It is primarily to avoid error prone code where tasks were not explicitly cancelled using task.cancel()
        task = self.__t
        try:
            return await asyncio.shield(task)
        finally:
            del task, self  # This is needed to avoid circular reference with raised exception

    @property
    def _asyncio_task(self) -> asyncio.Task[_T_co]:
        return self.__t


@final
class SystemTask(Task[_T_co], AbstractSystemTask[_T_co]):
    __slots__ = ()

    def __init__(self, coroutine: Coroutine[Any, Any, _T_co]) -> None:
        super().__init__(asyncio.create_task(coroutine))

    async def join_or_cancel(self) -> _T_co:
        task = self._asyncio_task
        try:
            return await task
        finally:
            del task, self  # This is needed to avoid circular reference with raised exception


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
        coro_func: Callable[_P, Coroutine[Any, Any, _T]],
        /,
        *args: _P.args,
        **kwargs: _P.kwargs,
    ) -> AbstractTask[_T]:
        return Task(self.__asyncio_tg.create_task(coro_func(*args, **kwargs)))

    def start_soon_with_context(
        self,
        context: contextvars.Context,
        coro_func: Callable[_P, Coroutine[Any, Any, _T]],
        /,
        *args: _P.args,
        **kwargs: _P.kwargs,
    ) -> AbstractTask[_T]:
        return Task(self.__asyncio_tg.create_task(coro_func(*args, **kwargs), context=context))


@final
class TimeoutHandle(AbstractTimeoutHandle):
    __slots__ = ("__handle", "__only_move_on", "__already_delayed_cancellation")

    __current_handle_dict: WeakKeyDictionary[asyncio.Task[Any], deque[TimeoutHandle]] = WeakKeyDictionary()
    __delayed_task_cancel_dict: WeakKeyDictionary[asyncio.Task[Any], asyncio.Handle] = WeakKeyDictionary()

    def __init__(self, handle: asyncio.Timeout, *, only_move_on: bool = False) -> None:
        super().__init__()
        self.__handle: asyncio.Timeout = handle
        self.__only_move_on: bool = bool(only_move_on)
        self.__already_delayed_cancellation: bool = True

    async def __aenter__(self) -> Self:
        timeout_handle: asyncio.Timeout = self.__handle
        await type(timeout_handle).__aenter__(timeout_handle)
        current_task = asyncio.current_task()
        assert current_task is not None  # nosec assert_used
        current_handle_dict = self.__current_handle_dict
        if current_task not in current_handle_dict:
            current_handle_dict[current_task] = deque()
            current_task.add_done_callback(current_handle_dict.pop)
        current_handle_dict[current_task].appendleft(self)
        self.__already_delayed_cancellation = current_task in self.__delayed_task_cancel_dict
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        timeout_handle: asyncio.Timeout = self.__handle
        current_task = asyncio.current_task()
        assert current_task is not None  # nosec assert_used
        try:
            await type(timeout_handle).__aexit__(timeout_handle, exc_type, exc_val, exc_tb)
        except TimeoutError:
            if self.__only_move_on:
                return True
            raise
        else:
            return None
        finally:
            delayed_task_cancel = None
            try:
                self.__current_handle_dict[current_task].popleft()
            except LookupError:  # pragma: no cover
                pass
            finally:
                if not self.__already_delayed_cancellation:
                    if not self.__current_handle_dict.get(current_task):
                        delayed_task_cancel = self.__delayed_task_cancel_dict.pop(current_task, None)
                    if delayed_task_cancel is not None:
                        delayed_task_cancel.cancel()
                del current_task, exc_val, exc_tb, self

    def when(self) -> float:
        deadline: float | None = self.__handle.when()
        return deadline if deadline is not None else math.inf

    def reschedule(self, when: float) -> None:
        return self.__handle.reschedule(self._cast_time(when))

    def expired(self) -> bool:
        return self.__handle.expired()

    @staticmethod
    def _cast_time(time_value: float) -> float | None:
        assert time_value is not None  # nosec assert_used
        return time_value if time_value != math.inf else None

    @classmethod
    def _reschedule_delayed_task_cancel(cls, task: asyncio.Task[Any], cancel_msg: str | None) -> None:
        task_cancel_handle = task.get_loop().call_soon(cls.__cancel_task_unless_done, task, cancel_msg)
        if cls.__current_handle_dict.get(task):
            if task in cls.__delayed_task_cancel_dict:
                cls.__delayed_task_cancel_dict[task].cancel()
            cls.__delayed_task_cancel_dict[task] = task_cancel_handle
        else:
            assert task not in cls.__delayed_task_cancel_dict  # nosec assert_used
            cls.__delayed_task_cancel_dict[task] = task_cancel_handle
            task.get_loop().call_soon(cls.__delayed_task_cancel_dict.pop, task, None)

    @staticmethod
    def __cancel_task_unless_done(task: asyncio.Task[Any], cancel_msg: str | None) -> None:
        if task.done():
            return
        task.uncancel()
        task.cancel(cancel_msg)


def timeout(delay: float) -> TimeoutHandle:
    return TimeoutHandle(asyncio.timeout(TimeoutHandle._cast_time(delay)))


def timeout_at(deadline: float) -> TimeoutHandle:
    return TimeoutHandle(asyncio.timeout_at(TimeoutHandle._cast_time(deadline)))


def move_on_after(delay: float) -> TimeoutHandle:
    return TimeoutHandle(asyncio.timeout(TimeoutHandle._cast_time(delay)), only_move_on=True)


def move_on_at(deadline: float) -> TimeoutHandle:
    return TimeoutHandle(asyncio.timeout_at(TimeoutHandle._cast_time(deadline)), only_move_on=True)
