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

__all__ = ["ThreadsPortal"]

import asyncio
import concurrent.futures
import contextlib
import contextvars
import inspect
from collections.abc import Awaitable, Callable
from types import TracebackType
from typing import ParamSpec, Self, TypeVar, final

from .... import _lock, _utils
from ...._final import runtime_final_class
from ..abc import ThreadsPortal as AbstractThreadsPortal
from .tasks import TaskUtils

_P = ParamSpec("_P")
_T = TypeVar("_T")


@final
@runtime_final_class
class ThreadsPortal(AbstractThreadsPortal):
    __slots__ = ("__loop", "__lock", "__task_group", "__call_soon_waiters")

    def __init__(self) -> None:
        super().__init__()
        self.__loop: asyncio.AbstractEventLoop | None = None
        self.__lock = _lock.ForkSafeLock()
        self.__task_group: asyncio.TaskGroup = asyncio.TaskGroup()
        self.__call_soon_waiters: set[asyncio.Future[None]] = set()

    async def __aenter__(self) -> Self:
        if self.__loop is not None:
            raise RuntimeError("ThreadsPortal entered twice.")
        await self.__task_group.__aenter__()
        self.__loop = asyncio.get_running_loop()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        try:
            with self.__lock.get():
                self.__loop = None

            while self.__call_soon_waiters:
                await TaskUtils.cancel_shielded_await(asyncio.wait(self.__call_soon_waiters))
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

        def on_fut_done(task: asyncio.Task[None], future: concurrent.futures.Future[_T]) -> None:
            if future.cancelled():
                with contextlib.suppress(RuntimeError):
                    loop = task.get_loop()
                    loop.call_soon_threadsafe(task.cancel)

        async def coroutine(waiter: asyncio.Future[None]) -> None:
            try:
                waiter.set_result(None)
                del waiter

                future.add_done_callback(_utils.prepend_argument(TaskUtils.current_asyncio_task(), on_fut_done))

                result = await coro_func(*args, **kwargs)
            except asyncio.CancelledError:
                future.cancel()
                future.set_running_or_notify_cancel()
                raise
            except BaseException as exc:
                if future.set_running_or_notify_cancel():
                    future.set_exception(exc)
                else:
                    loop = asyncio.get_running_loop()
                    loop.call_soon(
                        loop.call_exception_handler,
                        {
                            "message": "Task exception was not retrieved because future object is cancelled",
                            "exception": exc,
                            "task": TaskUtils.current_asyncio_task(loop),
                        },
                    )
            else:
                if future.set_running_or_notify_cancel():
                    future.set_result(result)

        def schedule_task() -> None:
            loop = asyncio.get_running_loop()
            waiter = self.__register_waiter(self.__call_soon_waiters, loop)
            _ = self.__task_group.create_task(coroutine(waiter), name=TaskUtils.compute_task_name_from_func(coro_func))

        self.run_sync_soon(schedule_task).result()
        return future

    def run_sync_soon(self, func: Callable[_P, _T], /, *args: _P.args, **kwargs: _P.kwargs) -> concurrent.futures.Future[_T]:
        import sniffio

        def callback() -> None:
            waiter.set_result(None)
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
            loop = self.__check_loop()
            waiter = self.__register_waiter(self.__call_soon_waiters, loop)

        ctx = contextvars.copy_context()
        ctx.run(sniffio.current_async_library_cvar.set, "asyncio")

        future: concurrent.futures.Future[_T] = concurrent.futures.Future()

        loop.call_soon_threadsafe(callback, context=ctx)
        return future

    def __check_loop(self) -> asyncio.AbstractEventLoop:
        loop = self.__loop
        if loop is None:
            raise RuntimeError("ThreadsPortal not running.")
        if self.__is_in_this_loop_thread(loop):
            raise RuntimeError("This function must be called in a different OS thread")
        return loop

    @staticmethod
    def __is_in_this_loop_thread(loop: asyncio.AbstractEventLoop) -> bool:
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            return False
        return running_loop is loop

    @staticmethod
    def __register_waiter(waiters: set[asyncio.Future[None]], loop: asyncio.AbstractEventLoop) -> asyncio.Future[None]:
        waiter: asyncio.Future[None] = loop.create_future()
        waiters.add(waiter)
        waiter.add_done_callback(waiters.discard)
        return waiter
