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

__all__ = ["CancelScope", "Task", "TaskGroup", "TaskUtils"]

import asyncio
import enum
import math
import types
from collections import deque
from collections.abc import Awaitable, Callable, Coroutine, Generator, Iterator
from types import TracebackType
from typing import Any, ClassVar, NamedTuple, Self, TypeVar, TypeVarTuple, cast, final
from weakref import WeakKeyDictionary

from .... import _utils
from ...._final import runtime_final_class
from ..abc import CancelScope as AbstractCancelScope, Task as AbstractTask, TaskGroup as AbstractTaskGroup, TaskInfo

_T = TypeVar("_T")
_T_co = TypeVar("_T_co", covariant=True)
_T_PosArgs = TypeVarTuple("_T_PosArgs")


@final
@runtime_final_class
class Task(AbstractTask[_T_co]):
    __slots__ = ("__task", "__h")

    def __init__(self, task: asyncio.Task[_T_co]) -> None:
        self.__task: asyncio.Task[_T_co] = task
        self.__h: int | None = None

    def __repr__(self) -> str:
        return f"<Task({self.__task})>"

    def __hash__(self) -> int:
        if (h := self.__h) is None:
            self.__h = h = hash((self.__class__, self.__task, 0xFF))
        return h

    def __eq__(self, other: object, /) -> bool:
        if not isinstance(other, Task):
            return NotImplemented
        return self.__task == other.__task

    @property
    def info(self) -> TaskInfo:
        return TaskUtils.create_task_info(self.__task)

    def done(self) -> bool:
        return self.__task.done()

    def cancel(self) -> bool:
        return self.__task.cancel()

    def cancelled(self) -> bool:
        return self.__task.cancelled()

    async def wait(self) -> None:
        task = self.__task
        if task.done():
            return

        waiter = asyncio.Event()

        def on_task_done(task: asyncio.Task[Any]) -> None:
            waiter.set()

        task.add_done_callback(on_task_done)
        try:
            await waiter.wait()
        finally:
            task.remove_done_callback(on_task_done)

    async def join(self) -> _T_co:
        try:
            return await asyncio.shield(self.__task)
        finally:
            del self  # This is needed to avoid circular reference with raised exception

    async def join_or_cancel(self) -> _T_co:
        try:
            return await self.__task
        finally:
            del self  # This is needed to avoid circular reference with raised exception


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
        except BaseExceptionGroup as exc_grp:
            if exc_val is not None and len(exc_grp.exceptions) == 1 and exc_grp.exceptions[0] is exc_val:
                # Do not raise inner exception within a group.
                return
            raise
        finally:
            del exc_val, exc_tb, asyncio_tg, self

    def start_soon(
        self,
        coro_func: Callable[[*_T_PosArgs], Coroutine[Any, Any, _T]],
        /,
        *args: *_T_PosArgs,
        name: str | None = None,
    ) -> None:
        coroutine = coro_func(*args)
        try:
            _ = self.__asyncio_tg.create_task(coroutine, name=name)
        except BaseException:
            coroutine.close()
            raise
        finally:
            del coroutine

    async def start(
        self,
        coro_func: Callable[[*_T_PosArgs], Coroutine[Any, Any, _T]],
        /,
        *args: *_T_PosArgs,
        name: str | None = None,
    ) -> AbstractTask[_T]:
        loop = asyncio.get_running_loop()
        waiter: asyncio.Future[None] = loop.create_future()

        coroutine = self.__task_coroutine(coro_func, args, waiter)
        try:
            asyncio_task = self.__asyncio_tg.create_task(coroutine, name=name)
        except BaseException:
            coroutine.close()
            raise
        else:
            task = Task(asyncio_task)
            del asyncio_task
        finally:
            del coroutine

        try:
            await waiter
        except asyncio.CancelledError:
            # Cancel the task and wait for it to exit before returning
            task.cancel()
            await TaskUtils.cancel_shielded_await(task.wait())
            raise
        finally:
            del waiter
        return task

    @staticmethod
    async def __task_coroutine(
        coro_func: Callable[[*_T_PosArgs], Awaitable[_T]],
        args: tuple[*_T_PosArgs],
        waiter: asyncio.Future[None],
    ) -> _T:
        if waiter.done():
            await asyncio.sleep(0)
        else:
            waiter.set_result(None)
        del waiter

        coroutine = coro_func(*args)
        del coro_func, args

        try:
            return await coroutine
        except BaseException as exc:
            _utils.remove_traceback_frames_in_place(exc, 1)
            raise
        finally:
            del coroutine


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
        "__host_task_cancelling",
        "__host_task_cancel_calls",
        "__state",
        "__cancel_called",
        "__cancelled_caught",
        "__deadline",
        "__timeout_handle",
        "__cancel_handle",
        "__delayed_cancellation_on_enter",
    )

    __current_task_scope_dict: ClassVar[WeakKeyDictionary[asyncio.Task[Any], deque[CancelScope]]] = WeakKeyDictionary()
    __delayed_task_cancel_dict: ClassVar[WeakKeyDictionary[asyncio.Task[Any], _DelayedCancel]] = WeakKeyDictionary()

    def __init__(self, *, deadline: float = math.inf) -> None:
        super().__init__()
        self.__host_task: asyncio.Task[Any] | None = None
        self.__host_task_cancelling: int = 0
        self.__host_task_cancel_calls: int = 0
        self.__state: _ScopeState = _ScopeState.CREATED
        self.__cancel_called: bool = False
        self.__cancelled_caught: bool = False
        self.__deadline: float = math.inf
        self.__timeout_handle: asyncio.Handle | None = None
        self.__cancel_handle: asyncio.Handle | None = None
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
        self.__host_task_cancelling = current_task.cancelling()

        current_task_scope = self.__current_task_scope_dict
        if current_task not in current_task_scope:
            current_task_scope[current_task] = deque()
            current_task.add_done_callback(current_task_scope.pop)
        current_task_scope[current_task].appendleft(self)

        self.__state = _ScopeState.ENTERED

        if self.__cancel_called:
            self.__deliver_cancellation()
        else:
            self.__setup_cancellation_by_timeout()
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

        if self.__cancel_handle:
            self.__cancel_handle.cancel()
            self.__cancel_handle = None

        host_task, self.__host_task = self.__host_task, None
        self.__current_task_scope_dict[host_task].popleft()

        should_suppress: bool = True
        if self.__cancel_called:
            while self.__host_task_cancel_calls:
                self.__host_task_cancel_calls -= 1
                if host_task.uncancel() <= self.__host_task_cancelling:
                    self.__host_task_cancel_calls = 0

            if exc_val is not None:
                is_my_cancellation: set[bool] = {
                    self.__is_my_cancellation_exception(exc) if isinstance(exc, asyncio.CancelledError) else False
                    for exc in _utils.iterate_exceptions(exc_val)
                }
                self.__cancelled_caught = any(is_my_cancellation)
                should_suppress = all(is_my_cancellation)

            delayed_task_cancel: _DelayedCancel | None = self.__delayed_task_cancel_dict.get(host_task, None)
            if delayed_task_cancel is not None and delayed_task_cancel.message == self.__cancellation_id():
                del self.__delayed_task_cancel_dict[host_task]
                delayed_task_cancel.handle.cancel()
                delayed_task_cancel = None

        self._check_pending_cancellation(host_task)

        return self.__cancelled_caught and should_suppress

    def __is_my_cancellation_exception(self, exc: asyncio.CancelledError) -> bool:
        # From https://github.com/agronholm/anyio/pull/790
        # Look at the previous ones in __context__ too for a matching cancel message.
        while True:
            if self.__cancellation_id() in exc.args:
                return True

            if isinstance(exc.__context__, asyncio.CancelledError):
                exc = exc.__context__
                continue

            return False

    def __deliver_cancellation(self) -> None:
        if self.__host_task is None:
            # Scope not active.
            return

        should_retry: bool = False
        if self.__host_task in self.__delayed_task_cancel_dict:
            delayed_task_cancel: _DelayedCancel = self.__delayed_task_cancel_dict[self.__host_task]
            if delayed_task_cancel.message == self.__cancellation_id():
                should_retry = True
        else:
            should_retry = True
            if not self.__task_must_cancel(self.__host_task) and self.__host_task is not asyncio.current_task():
                self.__host_task.cancel(msg=self.__cancellation_id())
                self.__host_task_cancel_calls += 1

        if should_retry:
            self.__cancel_handle = self.__host_task.get_loop().call_soon(self.__deliver_cancellation)
        else:
            self.__cancel_handle = None

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
            self.__setup_cancellation_by_timeout()

    def __setup_cancellation_by_timeout(self) -> None:
        if self.__deadline != math.inf:
            assert self.__host_task is not None  # nosec assert_used
            loop = self.__host_task.get_loop()
            if loop.time() >= self.__deadline:
                self.cancel()
            else:
                self.__timeout_handle = loop.call_at(self.__deadline, self.cancel)

    @classmethod
    def _current_task_scope(cls, task: asyncio.Task[Any]) -> CancelScope | None:
        return next(cls._inner_to_outer_task_scopes(task), None)

    @classmethod
    def _inner_to_outer_task_scopes(cls, task: asyncio.Task[Any]) -> Iterator[CancelScope]:
        return iter(cls.__current_task_scope_dict.get(task, ()))

    @classmethod
    def _reschedule_delayed_task_cancel(cls, task: asyncio.Task[Any], cancel_msg: str | None) -> asyncio.Handle:
        if task in cls.__delayed_task_cancel_dict:
            raise AssertionError("_reschedule_delayed_task_cancel() called too many times.")
        task_cancel_handle = task.get_loop().call_soon(cls.__cancel_task_unless_done, task, cancel_msg)
        cls.__delayed_task_cancel_dict[task] = _DelayedCancel(task_cancel_handle, cancel_msg)
        task.get_loop().call_soon(cls.__delayed_task_cancel_dict.pop, task, None)
        return task_cancel_handle

    @classmethod
    def _check_pending_cancellation(cls, host_task: asyncio.Task[Any]) -> None:
        for parent_scope in cls._inner_to_outer_task_scopes(host_task):
            if parent_scope.__cancel_called:
                if parent_scope.__cancel_handle is None:
                    parent_scope.__deliver_cancellation()
                break

    @staticmethod
    def __cancel_task_unless_done(task: asyncio.Task[Any], cancel_msg: str | None) -> None:
        if task.done():
            return
        task.uncancel()
        task.cancel(cancel_msg)

    @staticmethod
    def __task_must_cancel(task: asyncio.Task[Any]) -> bool:
        return getattr(task, "_must_cancel", False)


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

    @staticmethod
    @types.coroutine
    def coro_yield() -> Generator[Any, Any, None]:
        yield

    @classmethod
    async def cancel_shielded_coro_yield(cls) -> None:
        try:
            await cls.coro_yield()
        except asyncio.CancelledError as exc:
            CancelScope._reschedule_delayed_task_cancel(cls.current_asyncio_task(), _get_cancelled_error_message(exc))

    @classmethod
    def cancel_shielded_await(cls, awaitable: Awaitable[_T], /) -> Awaitable[_T]:
        return cast(Awaitable[_T], cls.__cancel_shielded_await(awaitable))

    @classmethod
    @types.coroutine
    def __cancel_shielded_await(cls, awaitable: Awaitable[_T], /) -> Generator[Any, Any, _T]:
        current_task: asyncio.Task[Any] = cls.current_asyncio_task()
        coroutine = awaitable.__await__()
        try:
            to_yield: asyncio.Future[Any] | None = coroutine.send(None)
        except StopIteration as exc:
            # Fast path.
            return exc.value
        except BaseException as exc:
            _utils.remove_traceback_frames_in_place(exc, 1)
            raise
        else:
            exc_to_throw: BaseException | None = None
            last_cancellation: asyncio.CancelledError | None = None
            while True:
                try:
                    if to_yield is None:
                        try:
                            yield None
                        except asyncio.CancelledError as exc:
                            last_cancellation = exc.with_traceback(None)
                    elif asyncio.isfuture(to_yield):
                        cls.__verify_yielded_future(to_yield, current_task)
                        while not to_yield.done():
                            try:
                                yield from asyncio.shield(to_yield)
                            except asyncio.CancelledError as exc:
                                last_cancellation = exc.with_traceback(None)
                        try:
                            to_yield.result()
                        except asyncio.CancelledError:
                            # inner future raises CancelledError, do not reschedule pending one.
                            last_cancellation = None
                            raise
                    else:
                        raise AssertionError(f"Task would get bad yield: {to_yield!r}")
                except GeneratorExit:  # pragma: no cover
                    raise
                except BaseException as exc:
                    exc_to_throw = _utils.remove_traceback_frames_in_place(exc, 1)
                finally:
                    del to_yield  # pragma: no branch

                if last_cancellation is not None:
                    CancelScope._reschedule_delayed_task_cancel(
                        current_task,
                        _get_cancelled_error_message(last_cancellation),
                    )
                last_cancellation = None
                try:
                    if exc_to_throw is None:
                        to_yield = coroutine.send(None)
                    else:
                        to_yield = coroutine.throw(exc_to_throw)
                except StopIteration as exc:
                    CancelScope._check_pending_cancellation(current_task)
                    return exc.value
                except BaseException as exc:
                    CancelScope._check_pending_cancellation(current_task)
                    _utils.remove_traceback_frames_in_place(exc, 1)
                    raise
                finally:
                    exc_to_throw = None
        finally:
            coroutine.close()
            del current_task, coroutine, awaitable

    @classmethod
    def __verify_yielded_future(cls, future: asyncio.Future[Any], current_task: asyncio.Task[Any]) -> None:
        # Reset blocking flag, because this future will not be sent directly to asyncio.Task
        future._asyncio_future_blocking = False

        if future is current_task:
            raise RuntimeError(f"Task cannot await on itself: {current_task!r}")

    @classmethod
    def create_task_info(cls, task: asyncio.Task[Any]) -> TaskInfo:
        return TaskInfo(id(task), task.get_name(), cast(Coroutine[Any, Any, Any] | None, task.get_coro()))

    @classmethod
    def compute_task_name_from_func(cls, func: Callable[..., Any]) -> str:
        return _utils.get_callable_name(func) or repr(func)


def _get_cancelled_error_message(exc: asyncio.CancelledError) -> str | None:
    msg: str | None
    if exc.args:
        msg = str(exc.args[0])
    else:
        msg = None
    return msg
