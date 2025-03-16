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

__all__ = ["CancelScope", "Task", "TaskGroup"]

import contextlib
import copy
import math
from collections.abc import Awaitable, Callable, Coroutine
from types import TracebackType
from typing import Any, Generic, Self, TypeVar, TypeVarTuple, final

import outcome
import trio

from .... import _utils
from ...._final import runtime_final_class
from ..abc import CancelScope as AbstractCancelScope, Task as AbstractTask, TaskGroup as AbstractTaskGroup, TaskInfo

_T = TypeVar("_T")
_T_co = TypeVar("_T_co", covariant=True)
_T_PosArgs = TypeVarTuple("_T_PosArgs")


@final
@runtime_final_class
class Task(AbstractTask[_T_co]):
    __slots__ = (
        "__task",
        "__scope",
        "__outcome",
    )

    def __init__(self, *, task: trio.lowlevel.Task, scope: trio.CancelScope, outcome: _OutcomeCell[_T_co]) -> None:
        self.__task: trio.lowlevel.Task = task
        self.__scope: trio.CancelScope = scope
        self.__outcome: _OutcomeCell[_T_co] = outcome

    def __repr__(self) -> str:
        return repr(self.__task)

    @property
    def info(self) -> TaskInfo:
        return TaskUtils.create_task_info(self.__task)

    def done(self) -> bool:
        return self.__outcome.peek() is not None

    def cancel(self) -> bool:
        if self.__outcome.peek() is None:
            self.__scope.cancel()
            return True
        return False

    def cancelled(self) -> bool:
        match self.__outcome.peek():
            case outcome.Error(trio.Cancelled()):
                return True
            case _:
                return False

    async def wait(self) -> None:
        await self.__outcome.get_no_checkpoints()

    async def join(self) -> _T_co:
        outcome = await self.__outcome.get_no_checkpoints()
        # Copy object because outcome objects can be unwrapped only once
        outcome = copy.copy(outcome)
        try:
            return outcome.unwrap()
        finally:
            del outcome, self  # This is needed to avoid circular reference with raised exception

    async def join_or_cancel(self) -> _T_co:
        try:
            outcome = await self.__outcome.get_no_checkpoints()
        except trio.Cancelled:
            self.__scope.cancel()
            with trio.CancelScope(shield=True):
                outcome = await self.__outcome.get_no_checkpoints()
            if self.cancelled():
                # Re-raise the current exception instead
                raise

        # Copy object because outcome objects can be unwrapped only once
        outcome = copy.copy(outcome)
        try:
            return outcome.unwrap()
        finally:
            del outcome, self  # This is needed to avoid circular reference with raised exception


@final
@runtime_final_class
class TaskGroup(AbstractTaskGroup):
    __slots__ = ("__nursery_ctx", "__nursery")

    def __init__(self) -> None:
        super().__init__()

        self.__nursery_ctx: contextlib.AbstractAsyncContextManager[trio.Nursery] = trio.open_nursery()
        self.__nursery: trio.Nursery | None = None

    async def __aenter__(self) -> Self:
        nursery_ctx = self.__nursery_ctx
        self.__nursery = await nursery_ctx.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        nursery_ctx = self.__nursery_ctx
        try:
            await nursery_ctx.__aexit__(exc_type, exc_val, exc_tb)
        except BaseExceptionGroup as exc_grp:
            if exc_val is not None and len(exc_grp.exceptions) == 1 and exc_grp.exceptions[0] is exc_val:
                # Do not raise inner exception within a group.
                return
            raise
        finally:
            del exc_val, exc_tb, nursery_ctx, self

    def start_soon(
        self,
        coro_func: Callable[[*_T_PosArgs], Coroutine[Any, Any, _T]],
        /,
        *args: *_T_PosArgs,
        name: str | None = None,
    ) -> None:
        nursery = self.__check_nursery_started()

        nursery.start_soon(coro_func, *args, name=name)

    async def start(
        self,
        coro_func: Callable[[*_T_PosArgs], Coroutine[Any, Any, _T]],
        /,
        *args: *_T_PosArgs,
        name: str | None = None,
    ) -> AbstractTask[_T]:
        nursery = self.__check_nursery_started()

        if name is None:
            name = TaskUtils.compute_task_name_from_func(coro_func)

        return await nursery.start(self.__task_coroutine, coro_func, args, name=name)  # type: ignore[return-value]

    def __check_nursery_started(self) -> trio.Nursery:
        if (n := self.__nursery) is None:
            raise RuntimeError("TaskGroup not started")
        return n

    @staticmethod
    async def __task_coroutine(
        coro_func: Callable[[*_T_PosArgs], Awaitable[_T]],
        args: tuple[*_T_PosArgs],
        *,
        task_status: trio.TaskStatus[Task[_T]],
    ) -> None:
        with trio.CancelScope() as scope:

            coroutine = coro_func(*args)
            del coro_func, args

            cell: _OutcomeCell[_T] = _OutcomeCell()

            task_status.started(
                Task(
                    task=trio.lowlevel.current_task(),
                    scope=scope,
                    outcome=cell,
                )
            )

            result: _T
            try:
                result = await coroutine
            except BaseException as exc:
                cell.set(outcome.Error(_utils.remove_traceback_frames_in_place(exc, 1)))
                raise
            else:
                cell.set(outcome.Value(result))
            finally:
                del coroutine


@final
@runtime_final_class
class CancelScope(AbstractCancelScope):
    __slots__ = ("__scope",)

    def __init__(self, *, deadline: float = math.inf) -> None:
        super().__init__()
        self.__validate_deadline(deadline)

        self.__scope: trio.CancelScope = trio.CancelScope(deadline=deadline)

    def __enter__(self) -> Self:
        scope = self.__scope
        type(scope).__enter__(scope)
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None) -> bool:
        scope = self.__scope
        try:
            return type(scope).__exit__(scope, exc_type, exc_val, exc_tb) or False
        finally:
            del exc_val, exc_tb, scope, self

    def cancel(self) -> None:
        return self.__scope.cancel()

    def cancel_called(self) -> bool:
        return self.__scope.cancel_called

    def cancelled_caught(self) -> bool:
        return self.__scope.cancelled_caught

    def when(self) -> float:
        return self.__scope.deadline

    def reschedule(self, when: float, /) -> None:
        self.__validate_deadline(when)
        self.__scope.deadline = when

    def __validate_deadline(self, when: float) -> None:
        if math.isnan(when):
            raise ValueError("deadline is NaN")


@final
@runtime_final_class
class TaskUtils:

    @classmethod
    def create_task_info(cls, task: trio.lowlevel.Task) -> TaskInfo:
        return TaskInfo(id(task), task.name, task.coro)

    @classmethod
    def compute_task_name_from_func(cls, func: Callable[..., Any]) -> str:
        return _utils.get_callable_name(func) or repr(func)


class _OutcomeCell(Generic[_T_co]):
    __slots__ = (
        "__result",
        "__waiting_tasks",
    )

    def __init__(self) -> None:
        self.__result: outcome.Outcome[_T_co] | None = None
        self.__waiting_tasks: set[trio.lowlevel.Task] = set()

    def peek(self) -> outcome.Outcome[_T_co] | None:
        return self.__result

    def get_nowait(self) -> outcome.Outcome[_T_co]:
        if (result := self.__result) is None:
            raise trio.WouldBlock
        return result

    async def get_no_checkpoints(self) -> outcome.Outcome[_T_co]:
        try:
            result = self.get_nowait()
        except trio.WouldBlock:
            pass
        else:
            return result

        task = trio.lowlevel.current_task()
        self.__waiting_tasks.add(task)

        def abort_fn(_: Any) -> trio.lowlevel.Abort:
            self.__waiting_tasks.discard(task)
            return trio.lowlevel.Abort.SUCCEEDED

        return await trio.lowlevel.wait_task_rescheduled(abort_fn)

    def set(self, result: outcome.Outcome[_T_co]) -> None:
        if self.__result is not None:
            raise AssertionError("Already set to a value")

        self.__result = result

        for task in self.__waiting_tasks:
            trio.lowlevel.reschedule(task, outcome.Value(result))

        self.__waiting_tasks.clear()
