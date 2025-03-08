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

__all__ = ["ThreadsPortal"]

import concurrent.futures
import contextlib
import contextvars
import inspect
import threading
from collections.abc import Awaitable, Callable
from types import TracebackType
from typing import ParamSpec, Self, TypeVar, final

import trio

from .... import _lock, _utils
from ...._final import runtime_final_class
from ..abc import ThreadsPortal as AbstractThreadsPortal
from .tasks import TaskGroup, TaskUtils

_P = ParamSpec("_P")
_T = TypeVar("_T")


@final
@runtime_final_class
class ThreadsPortal(AbstractThreadsPortal):
    __slots__ = ("__trio_token", "__lock", "__run_sync_soon_waiter", "__task_group")

    def __init__(self) -> None:
        super().__init__()

        self.__lock = _lock.ForkSafeLock()
        self.__trio_token: trio.lowlevel.TrioToken | None = None
        self.__task_group: TaskGroup = TaskGroup()
        self.__run_sync_soon_waiter = _PortalRunSyncSoonWaiter()

    async def __aenter__(self) -> Self:
        if self.__trio_token is not None:
            raise RuntimeError("ThreadsPortal entered twice.")
        await self.__task_group.__aenter__()
        self.__trio_token = trio.lowlevel.current_trio_token()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        try:
            with self.__lock.get():
                self.__trio_token = None

            with trio.CancelScope(shield=True):
                await self.__run_sync_soon_waiter.aclose()
            await self.__task_group.__aexit__(exc_type, exc_val, exc_tb)
        finally:
            del self, exc_val, exc_tb

    def run_coroutine_soon(
        self,
        coro_func: Callable[_P, Awaitable[_T]],
        /,
        *args: _P.args,
        **kwargs: _P.kwargs,
    ) -> concurrent.futures.Future[_T]:

        future: concurrent.futures.Future[_T] = concurrent.futures.Future()

        def on_fut_done(payload: tuple[trio.lowlevel.TrioToken, trio.CancelScope], future: concurrent.futures.Future[_T]) -> None:
            if future.cancelled():
                with contextlib.suppress(RuntimeError):
                    trio_token, cancel_scope = payload
                    trio_token.run_sync_soon(cancel_scope.cancel)

        def exception_handler(task: trio.lowlevel.Task, exc: BaseException) -> None:
            import logging

            logger = logging.getLogger("trio")

            log_lines = [
                "Task exception was not retrieved because future object is cancelled",
                f"task: {task!r}",
            ]

            logger.error("\n".join(log_lines), exc_info=exc)

        async def coroutine() -> None:
            with trio.CancelScope() as scope:
                try:
                    future.add_done_callback(_utils.prepend_argument((trio.lowlevel.current_trio_token(), scope), on_fut_done))

                    result = await coro_func(*args, **kwargs)
                except trio.Cancelled:
                    future.cancel()
                    future.set_running_or_notify_cancel()
                    raise
                except BaseException as exc:
                    if future.set_running_or_notify_cancel():
                        future.set_exception(exc)
                    else:
                        exception_handler(trio.lowlevel.current_task(), exc)
                else:
                    if future.set_running_or_notify_cancel():
                        future.set_result(result)

        def schedule_task() -> None:
            self.__task_group.start_soon(coroutine, name=TaskUtils.compute_task_name_from_func(coro_func))

        self.run_sync_soon(schedule_task).result()
        return future

    def run_sync_soon(self, func: Callable[_P, _T], /, *args: _P.args, **kwargs: _P.kwargs) -> concurrent.futures.Future[_T]:
        import sniffio

        run_sync_soon_waiter = self.__run_sync_soon_waiter
        future: concurrent.futures.Future[_T] = concurrent.futures.Future()

        @trio.lowlevel.enable_ki_protection
        def callback() -> None:
            run_sync_soon_waiter.detach_in_trio_thread()
            if not future.set_running_or_notify_cancel():
                return
            try:
                result = func(*args, **kwargs)
                if inspect.iscoroutine(result):
                    result.close()  # Prevent ResourceWarnings
                    msg = "func is a coroutine function."
                    note = "You should use run_coroutine() or run_coroutine_soon() instead."
                    raise _utils.exception_with_notes(TypeError(msg), note)
            except BaseException as exc:
                future.set_exception(exc)
            else:
                future.set_result(result)

        with self.__lock.get():
            trio_token = self.__check_current_token()
            run_sync_soon_waiter.attach_from_any_thread()

        ctx: contextvars.Context = contextvars.copy_context()
        # trio already sets sniffio.thread_local.name
        ctx.run(sniffio.current_async_library_cvar.set, None)

        trio_token.run_sync_soon(ctx.run, callback)
        return future

    def __check_current_token(self) -> trio.lowlevel.TrioToken:
        trio_token = self.__trio_token
        if trio_token is None:
            raise RuntimeError("ThreadsPortal not running.")
        if self.__is_in_this_loop_thread(trio_token):
            raise RuntimeError("This function must be called in a different OS thread")
        return trio_token

    @staticmethod
    def __is_in_this_loop_thread(trio_token: trio.lowlevel.TrioToken) -> bool:
        try:
            current_trio_token = trio.lowlevel.current_trio_token()
        except RuntimeError:
            return False
        return current_trio_token is trio_token


class _PortalRunSyncSoonWaiter:
    __slots__ = ("__done", "__thread_lock", "__waiter_count", "__closing")

    def __init__(self) -> None:
        self.__done: trio.Event = trio.Event()
        self.__thread_lock = _lock.ForkSafeLock(threading.Lock)
        self.__waiter_count: int = 0
        self.__closing: bool = False

    async def aclose(self) -> None:
        with self.__thread_lock.get():
            self.__closing = True
            if not self.__waiter_count:
                self.__done.set()

        await self.__done.wait()

    def attach_from_any_thread(self) -> None:
        with self.__thread_lock.get():
            if self.__done.is_set():
                raise AssertionError("currently closed")
            self.__waiter_count += 1

    @trio.lowlevel.enable_ki_protection
    def detach_in_trio_thread(self) -> None:
        with self.__thread_lock.get():
            self.__waiter_count -= 1
            if self.__waiter_count < 0:
                raise AssertionError("self.__waiter_count < 0")
            if not self.__waiter_count and self.__closing:
                self.__done.set()
