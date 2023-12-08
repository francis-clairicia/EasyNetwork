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

__all__ = ["CancelScope", "Task", "TaskGroup", "TaskUtils"]

import asyncio
import contextvars
import enum
import math
from collections import deque
from collections.abc import Callable, Coroutine, Iterable, Iterator
from typing import TYPE_CHECKING, Any, NamedTuple, Self, TypeVar, final
from weakref import WeakKeyDictionary

from .._final import runtime_final_class
from ..api_async.backend.abc import CancelScope as AbstractCancelScope, Task as AbstractTask, TaskGroup as AbstractTaskGroup

if TYPE_CHECKING:
    from types import TracebackType


_T = TypeVar("_T")
_T_co = TypeVar("_T_co", covariant=True)


@final
@runtime_final_class
class Task(AbstractTask[_T_co]):
    __slots__ = ("__t", "__h")

    def __init__(self, task: asyncio.Task[_T_co]) -> None:
        self.__t: asyncio.Task[_T_co] = task
        self.__h: int | None = None

    def __repr__(self) -> str:
        return f"<Task({self.__t})>"

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
        await asyncio.wait({task})

    async def join(self) -> _T_co:
        task = self.__t
        try:
            return await asyncio.shield(task)
        finally:
            del task, self  # This is needed to avoid circular reference with raised exception

    async def join_or_cancel(self) -> _T_co:
        task = self.__t
        try:
            return await task
        finally:
            del task, self  # This is needed to avoid circular reference with raised exception


@final
@runtime_final_class
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
        coro_func: Callable[..., Coroutine[Any, Any, _T]],
        /,
        *args: Any,
        context: contextvars.Context | None = None,
    ) -> AbstractTask[_T]:
        return Task(self.__asyncio_tg.create_task(coro_func(*args), context=context))


class _ScopeState(enum.Enum):
    CREATED = "created"
    ENTERED = "entered"
    EXITED = "exited"


class _DelayedCancel(NamedTuple):
    handle: asyncio.Handle
    message: str | None


@final
@runtime_final_class
class CancelScope(AbstractCancelScope):
    __slots__ = (
        "__host_task",
        "__state",
        "__cancel_called",
        "__cancelled_caught",
        "__deadline",
        "__timeout_handle",
        "__delayed_cancellation_on_enter",
    )

    __current_task_scope_dict: WeakKeyDictionary[asyncio.Task[Any], deque[CancelScope]] = WeakKeyDictionary()
    __delayed_task_cancel_dict: WeakKeyDictionary[asyncio.Task[Any], _DelayedCancel] = WeakKeyDictionary()

    def __init__(self, *, deadline: float = math.inf) -> None:
        super().__init__()
        self.__host_task: asyncio.Task[Any] | None = None
        self.__state: _ScopeState = _ScopeState.CREATED
        self.__cancel_called: bool = False
        self.__cancelled_caught: bool = False
        self.__deadline: float = math.inf
        self.__timeout_handle: asyncio.Handle | None = None
        self.reschedule(deadline)

    def __repr__(self) -> str:
        active = self.__state is _ScopeState.ENTERED
        cancel_called = self.__cancel_called
        cancelled_caught = self.__cancelled_caught
        host_task = self.__host_task
        deadline = self.__deadline

        info = f"{active=!r}, {cancelled_caught=!r}, {cancel_called=!r}, {host_task=!r}, {deadline=!r}"
        return f"<{self.__class__.__name__}({info})>"

    def __enter__(self) -> Self:
        if self.__state is not _ScopeState.CREATED:
            raise RuntimeError("CancelScope entered twice")

        self.__host_task = current_task = TaskUtils.current_asyncio_task()

        current_task_scope = self.__current_task_scope_dict
        if current_task not in current_task_scope:
            current_task_scope[current_task] = deque()
            current_task.add_done_callback(current_task_scope.pop)
        current_task_scope[current_task].appendleft(self)

        self.__state = _ScopeState.ENTERED

        if self.__cancel_called:
            self.__deliver_cancellation()
        else:
            self.__timeout()
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None) -> bool:
        if self.__state is not _ScopeState.ENTERED:
            raise RuntimeError("This cancel scope is not active")

        if TaskUtils.current_asyncio_task() is not self.__host_task:
            raise RuntimeError("Attempted to exit cancel scope in a different task than it was entered in")

        if self._current_task_scope(self.__host_task) is not self:
            raise RuntimeError("Attempted to exit a cancel scope that isn't the current tasks's current cancel scope")

        self.__state = _ScopeState.EXITED

        if self.__timeout_handle:
            self.__timeout_handle.cancel()
            self.__timeout_handle = None

        host_task, self.__host_task = self.__host_task, None
        self.__current_task_scope_dict[host_task].popleft()

        if self.__cancel_called:
            task_cancelling = host_task.uncancel()
            if isinstance(exc_val, asyncio.CancelledError):
                self.__cancelled_caught = self.__cancellation_id() in exc_val.args

            delayed_task_cancel = self.__delayed_task_cancel_dict.get(host_task, None)
            if delayed_task_cancel is not None and delayed_task_cancel.message == self.__cancellation_id():
                del self.__delayed_task_cancel_dict[host_task]
                delayed_task_cancel.handle.cancel()
                delayed_task_cancel = None

            if delayed_task_cancel is None:
                for cancel_scope in self._inner_to_outer_task_scopes(host_task):
                    if cancel_scope.__cancel_called:
                        self._reschedule_delayed_task_cancel(host_task, cancel_scope.__cancellation_id())
                        break
                else:
                    if task_cancelling > 0:
                        self._reschedule_delayed_task_cancel(host_task, None)

        return self.__cancelled_caught

    def __deliver_cancellation(self) -> None:
        if self.__host_task is None:
            # Scope not active.
            return
        try:
            self.__delayed_task_cancel_dict.pop(self.__host_task).handle.cancel()
        except KeyError:
            pass
        self.__host_task.cancel(msg=self.__cancellation_id())

    def __cancellation_id(self) -> str:
        return f"Cancelled by cancel scope {id(self):x}"

    def cancel(self) -> None:
        if not self.__cancel_called:
            self.__cancel_called = True
            if self.__timeout_handle:
                self.__timeout_handle.cancel()
                self.__timeout_handle = None
            self.__deliver_cancellation()

    def cancel_called(self) -> bool:
        return self.__cancel_called

    def cancelled_caught(self) -> bool:
        return self.__cancelled_caught

    def when(self) -> float:
        return self.__deadline

    def reschedule(self, when: float, /) -> None:
        if math.isnan(when):
            raise ValueError("deadline is NaN")
        self.__deadline = max(when, 0)
        if self.__timeout_handle:
            self.__timeout_handle.cancel()
            self.__timeout_handle = None
        if self.__state is _ScopeState.ENTERED and not self.__cancel_called:
            self.__timeout()

    def __timeout(self) -> None:
        if self.__deadline != math.inf:
            assert self.__host_task is not None  # nosec assert_used
            loop = self.__host_task.get_loop()
            if loop.time() >= self.__deadline:
                self.__timeout_handle = loop.call_soon(self.cancel)
            else:
                self.__timeout_handle = loop.call_at(self.__deadline, self.cancel)

    @classmethod
    def _current_task_scope(cls, task: asyncio.Task[Any]) -> CancelScope | None:
        try:
            return cls.__current_task_scope_dict[task][0]
        except LookupError:
            return None

    @classmethod
    def _inner_to_outer_task_scopes(cls, task: asyncio.Task[Any]) -> Iterator[CancelScope]:
        if cls._current_task_scope(task) is None:
            return iter(())
        return iter(cls.__current_task_scope_dict[task])

    @classmethod
    def _reschedule_delayed_task_cancel(cls, task: asyncio.Task[Any], cancel_msg: str | None) -> asyncio.Handle:
        if task in cls.__delayed_task_cancel_dict:
            raise RuntimeError("CancelScope issue.")  # pragma: no cover
        task_cancel_handle = task.get_loop().call_soon(cls.__cancel_task_unless_done, task, cancel_msg)
        cls.__delayed_task_cancel_dict[task] = _DelayedCancel(task_cancel_handle, cancel_msg)
        task.get_loop().call_soon(cls.__delayed_task_cancel_dict.pop, task, None)
        return task_cancel_handle

    @staticmethod
    def __cancel_task_unless_done(task: asyncio.Task[Any], cancel_msg: str | None) -> None:
        if task.done():
            return
        task.uncancel()
        task.cancel(cancel_msg)


@final
@runtime_final_class
class TaskUtils:
    @staticmethod
    def check_current_event_loop(loop: asyncio.AbstractEventLoop) -> None:
        running_loop = asyncio.get_running_loop()
        if running_loop is not loop:
            raise RuntimeError(f"{running_loop=!r} is not {loop=!r}")

    @staticmethod
    def current_asyncio_task(loop: asyncio.AbstractEventLoop | None = None) -> asyncio.Task[Any]:
        t: asyncio.Task[Any] | None = asyncio.current_task(loop=loop)
        if t is None:
            raise RuntimeError("This function should be called within a task.")
        return t

    @classmethod
    async def cancel_shielded_wait_asyncio_futures(
        cls,
        fs: Iterable[asyncio.Future[Any]],
        *,
        abort_func: Callable[[], bool] | None = None,
    ) -> asyncio.Handle | None:
        fs = set(fs)
        current_task: asyncio.Task[Any] = cls.current_asyncio_task()
        abort: bool | None = None
        task_cancelled: bool = False
        task_cancel_msg: str | None = None

        try:
            _schedule_task_discard(fs)
            while fs:
                try:
                    await asyncio.wait(fs)
                except asyncio.CancelledError as exc:
                    if abort is None:
                        if abort_func is None:
                            abort = False
                        else:
                            abort = bool(abort_func())
                    if abort:
                        raise
                    task_cancelled = True
                    task_cancel_msg = _get_cancelled_error_message(exc)

            if task_cancelled:
                return CancelScope._reschedule_delayed_task_cancel(current_task, task_cancel_msg)
            return None
        finally:
            del current_task, fs, abort_func
            task_cancel_msg = None

    @classmethod
    async def cancel_shielded_coro_yield(cls) -> None:
        current_task: asyncio.Task[Any] = cls.current_asyncio_task()
        try:
            await asyncio.sleep(0)
        except asyncio.CancelledError as exc:
            CancelScope._reschedule_delayed_task_cancel(current_task, _get_cancelled_error_message(exc))
        finally:
            del current_task

    @classmethod
    async def cancel_shielded_await_task(cls, task: asyncio.Task[_T_co]) -> _T_co:
        # This task must be unregistered in order not to be cancelled by runner at event loop shutdown
        asyncio._unregister_task(task)

        try:
            current_task_cancel_handle = await cls.cancel_shielded_wait_asyncio_futures({task})
            if current_task_cancel_handle is not None and task.cancelled():
                current_task_cancel_handle.cancel()
            return task.result()
        finally:
            del task


def _get_cancelled_error_message(exc: asyncio.CancelledError) -> str | None:
    msg: str | None
    if exc.args:
        msg = exc.args[0]
    else:
        msg = None
    return msg


def _schedule_task_discard(fs: set[asyncio.Future[Any]]) -> None:
    for f in fs:
        f.add_done_callback(fs.discard)
