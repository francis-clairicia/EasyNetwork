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
import inspect
import math
import types
from collections import deque
from collections.abc import Awaitable, Callable, Coroutine, Generator, Iterable, Iterator
from typing import TYPE_CHECKING, Any, ClassVar, NamedTuple, Self, TypeVar, cast, final
from weakref import WeakKeyDictionary

from .. import _utils
from .._final import runtime_final_class
from ..api_async.backend.abc import (
    CancelScope as AbstractCancelScope,
    Task as AbstractTask,
    TaskGroup as AbstractTaskGroup,
    TaskInfo,
)

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

    @property
    def info(self) -> TaskInfo:
        return TaskUtils.create_task_info(self.__t)

    def done(self) -> bool:
        return self.__t.done()

    def cancel(self) -> bool:
        return self.__t.cancel()

    def cancelled(self) -> bool:
        return self.__t.cancelled()

    async def wait(self) -> None:
        task = self.__t
        if task.done():
            return
        try:
            waiter = asyncio.Event()

            def on_task_done(task: asyncio.Task[Any]) -> None:
                waiter.set()

            task.add_done_callback(on_task_done)
            try:
                await waiter.wait()
            finally:
                task.remove_done_callback(on_task_done)
        finally:
            del task, self  # This is needed to avoid circular reference with raised exception

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
        coro_func: Callable[..., Coroutine[Any, Any, Any]],
        /,
        *args: Any,
        name: str | None = None,
    ) -> None:
        name = TaskUtils.compute_task_name_from_func(coro_func) if name is None else str(name)
        coroutine = TaskUtils.ensure_coroutine(coro_func, args)
        _ = self.__asyncio_tg.create_task(coroutine, name=name)

    async def start(
        self,
        coro_func: Callable[..., Coroutine[Any, Any, _T]],
        /,
        *args: Any,
        name: str | None = None,
    ) -> AbstractTask[_T]:
        loop = asyncio.get_running_loop()
        waiter: asyncio.Future[None] = loop.create_future()

        name = TaskUtils.compute_task_name_from_func(coro_func) if name is None else str(name)
        coroutine = TaskUtils.ensure_coroutine(coro_func, args)
        task = Task(self.__asyncio_tg.create_task(self.__task_coroutine(coroutine, waiter), name=name))
        del coroutine

        try:
            await waiter
        finally:
            del waiter
        return task

    @staticmethod
    async def __task_coroutine(
        coroutine: Coroutine[Any, Any, _T],
        waiter: asyncio.Future[None],
    ) -> _T:
        try:
            try:
                if not waiter.done():
                    waiter.set_result(None)
            finally:
                del waiter
            return await coroutine
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

        if self.__cancel_called:
            if exc_val is not None:
                self.__cancelled_caught = any(
                    self.__uncancel_task(host_task, exc)
                    for exc in _utils.iterate_exceptions(exc_val)
                    if isinstance(exc, asyncio.CancelledError)
                )

            delayed_task_cancel: _DelayedCancel | None = self.__delayed_task_cancel_dict.get(host_task, None)
            if delayed_task_cancel is not None and delayed_task_cancel.message == self.__cancellation_id():
                del self.__delayed_task_cancel_dict[host_task]
                delayed_task_cancel.handle.cancel()
                delayed_task_cancel = None

        for parent_scope in self._inner_to_outer_task_scopes(host_task):
            if parent_scope.__cancel_called:
                if parent_scope.__cancel_handle is None:
                    parent_scope.__deliver_cancellation()
                break

        return self.__cancelled_caught

    def __uncancel_task(self, host_task: asyncio.Task[Any], exc: asyncio.CancelledError) -> bool:
        while self.__host_task_cancel_calls:
            self.__host_task_cancel_calls -= 1
            if host_task.uncancel() <= self.__host_task_cancelling:
                return True
        return self.__cancellation_id() in exc.args

    def __deliver_cancellation(self) -> None:
        if self.__host_task is None:
            # Scope not active.
            return

        should_retry: bool = False

        if not self.__task_must_cancel(self.__host_task) and self.__host_task not in self.__delayed_task_cancel_dict:
            should_retry = True
            if self.__host_task is not asyncio.current_task():
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
            raise AssertionError("_reschedule_delayed_task_cancel() called too many times.")
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

    @classmethod
    @types.coroutine
    def coro_yield(cls) -> Generator[Any, Any, None]:
        yield

    @classmethod
    async def cancel_shielded_wait_asyncio_futures(cls, fs: Iterable[asyncio.Future[Any]]) -> asyncio.Handle | None:
        fs = set(fs)
        current_task: asyncio.Task[Any] = cls.current_asyncio_task()
        task_cancelled: bool = False
        task_cancel_msg: str | None = None

        try:
            _schedule_task_discard(fs)
            # Open a scope in order to check pending cancellations at the end.
            with CancelScope():
                while fs:
                    try:
                        await asyncio.wait(fs)
                    except asyncio.CancelledError as exc:
                        task_cancelled = True
                        task_cancel_msg = _get_cancelled_error_message(exc)

                if task_cancelled:
                    return CancelScope._reschedule_delayed_task_cancel(current_task, task_cancel_msg)
            return None
        finally:
            del current_task, fs
            task_cancel_msg = None

    @classmethod
    async def cancel_shielded_await_future(cls, future: asyncio.Future[_T_co]) -> _T_co:
        loop = asyncio.get_running_loop()
        current_task: asyncio.Task[Any] = cls.current_asyncio_task(loop)
        task_cancelled: bool = False
        task_cancel_msg: str | None = None
        try:
            done_event = asyncio.Event()
            future.add_done_callback(lambda _: done_event.set())

            # Open a scope in order to check pending cancellations at the end.
            with CancelScope():
                while not done_event.is_set():
                    try:
                        await done_event.wait()
                    except asyncio.CancelledError as exc:
                        task_cancelled = True
                        task_cancel_msg = _get_cancelled_error_message(exc)

                if task_cancelled:
                    CancelScope._reschedule_delayed_task_cancel(current_task, task_cancel_msg)
                    if future.cancelled():
                        await cls.coro_yield()
            return future.result()
        finally:
            del current_task, future
            task_cancel_msg = None

    @classmethod
    async def cancel_shielded_coro_yield(cls) -> None:
        current_task: asyncio.Task[Any] = cls.current_asyncio_task()
        try:
            await cls.coro_yield()
        except asyncio.CancelledError as exc:
            CancelScope._reschedule_delayed_task_cancel(current_task, _get_cancelled_error_message(exc))
        finally:
            del current_task

    @classmethod
    async def cancel_shielded_await(cls, coroutine: Awaitable[_T_co]) -> _T_co:
        coroutine = cls.wrap_awaitable(coroutine)
        loop = asyncio.get_running_loop()
        current_task_context = cls.get_task_context(cls.current_asyncio_task(loop))

        def copy_future_state(waiter: asyncio.Future[_T_co], task: asyncio.Task[_T_co]) -> None:
            if waiter.done():
                raise AssertionError("waiter should not be done")
            if task.cancelled():
                waiter.cancel()
            elif (exc := task.exception()) is not None:
                waiter.set_exception(exc)
            else:
                waiter.set_result(task.result())

        def schedule_task(coroutine: Coroutine[Any, Any, _T_co], waiter: asyncio.Future[_T_co]) -> None:
            try:
                task = loop.create_task(coroutine, context=current_task_context)
            except BaseException as exc:
                waiter.set_exception(exc)
                coroutine.close()
            else:
                if task.done():  # eager task done
                    copy_future_state(waiter, task)
                else:
                    task.add_done_callback(_utils.prepend_argument(waiter, copy_future_state))
                    # This task must be unregistered in order not to be cancelled by runner at event loop shutdown
                    asyncio._unregister_task(task)

        waiter: asyncio.Future[_T_co] = loop.create_future()
        loop.call_soon(schedule_task, coroutine, waiter)
        del coroutine
        try:
            return await cls.cancel_shielded_await_future(waiter)
        finally:
            del waiter

    @classmethod
    def ensure_coroutine(
        cls,
        coro_func: Callable[..., Coroutine[Any, Any, _T]],
        args: tuple[Any, ...],
    ) -> Coroutine[Any, Any, _T]:
        coro = coro_func(*args)
        if not isinstance(coro, Coroutine):
            raise TypeError(f"A coroutine was expected, got {coro!r}")
        return coro

    @classmethod
    def wrap_awaitable(cls, coroutine: Awaitable[_T]) -> Coroutine[Any, Any, _T]:
        if not inspect.isawaitable(coroutine):
            raise TypeError("Expected an awaitable object")

        if not isinstance(coroutine, Coroutine):

            async def coro_wrapper(coroutine: Awaitable[_T]) -> _T:
                return await coroutine

            coroutine = coro_wrapper(coroutine)
            del coro_wrapper

        return coroutine

    @classmethod
    def create_task_info(cls, task: asyncio.Task[Any]) -> TaskInfo:
        return TaskInfo(id(task), task.get_name(), cast(Coroutine[Any, Any, Any] | None, task.get_coro()))

    @classmethod
    def compute_task_name_from_func(cls, func: Callable[..., Any]) -> str:
        return _utils.get_callable_name(func) or repr(func)

    @classmethod
    def get_task_context(cls, task: asyncio.Task[Any]) -> contextvars.Context | None:
        try:
            get_context: Callable[[], contextvars.Context] = getattr(task, "get_context")
        except AttributeError:
            return None
        return get_context()


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
