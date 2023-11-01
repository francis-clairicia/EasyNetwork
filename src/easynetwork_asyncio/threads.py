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

__all__ = ["ThreadsPortal"]

import asyncio
import concurrent.futures
import contextvars
import inspect
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, ParamSpec, Self, TypeVar, final

from easynetwork.lowlevel._lock import ForkSafeLock
from easynetwork.lowlevel._utils import exception_with_notes as _exception_with_notes
from easynetwork.lowlevel.api_async.backend.abc import ThreadsPortal as AbstractThreadsPortal
from easynetwork.lowlevel.api_async.backend.sniffio import current_async_library_cvar as _sniffio_current_async_library_cvar

from .tasks import TaskUtils

if TYPE_CHECKING:
    from types import TracebackType

_P = ParamSpec("_P")
_T = TypeVar("_T")


@final
class ThreadsPortal(AbstractThreadsPortal):
    __slots__ = ("__loop", "__lock", "__task_group", "__call_soon_waiters")

    def __init__(self) -> None:
        super().__init__()
        self.__loop: asyncio.AbstractEventLoop | None = None
        self.__lock = ForkSafeLock()
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
                await TaskUtils.cancel_shielded_wait_asyncio_futures(self.__call_soon_waiters)
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
        def schedule_task() -> concurrent.futures.Future[_T]:
            future: concurrent.futures.Future[_T] = concurrent.futures.Future()

            async def coroutine() -> None:
                def on_fut_done(future: concurrent.futures.Future[_T]) -> None:
                    if future.cancelled():
                        try:
                            self.run_sync(task.cancel)
                        except RuntimeError:
                            # on_fut_done() called from coroutine()
                            # or the portal is already shut down
                            pass

                task = TaskUtils.current_asyncio_task()
                try:
                    if future.cancelled():
                        task.cancel()
                    else:
                        future.add_done_callback(on_fut_done)
                    result = await coro_func(*args, **kwargs)
                except asyncio.CancelledError:
                    future.cancel()
                    future.set_running_or_notify_cancel()
                    raise
                except BaseException as exc:
                    if future.set_running_or_notify_cancel():
                        future.set_exception(exc)
                    if not isinstance(exc, Exception):
                        raise  # pragma: no cover
                else:
                    if future.set_running_or_notify_cancel():
                        future.set_result(result)

            task = self.__task_group.create_task(coroutine())
            loop = task.get_loop()
            del task
            with self.__lock.get():
                loop.call_soon(self.__register_waiter(self.__call_soon_waiters, loop).set_result, None)
            return future

        return self.run_sync(schedule_task)

    def run_sync_soon(self, func: Callable[_P, _T], /, *args: _P.args, **kwargs: _P.kwargs) -> concurrent.futures.Future[_T]:
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
                    raise _exception_with_notes(TypeError(msg), note)
            except BaseException as exc:
                future.set_exception(exc)
                if isinstance(exc, (SystemExit, KeyboardInterrupt)):
                    raise  # pragma: no cover
            else:
                future.set_result(result)

        with self.__lock.get():
            loop = self.__check_loop()
            waiter = self.__register_waiter(self.__call_soon_waiters, loop)

        ctx = contextvars.copy_context()

        if _sniffio_current_async_library_cvar is not None:
            ctx.run(_sniffio_current_async_library_cvar.set, "asyncio")

        future: concurrent.futures.Future[_T] = concurrent.futures.Future()

        loop.call_soon_threadsafe(callback, context=ctx)
        return future

    def __check_loop(self) -> asyncio.AbstractEventLoop:
        loop = self.__loop
        if loop is None:
            raise RuntimeError("ThreadsPortal not running.")
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            return loop
        if running_loop is loop:
            raise RuntimeError("This function must be called in a different OS thread")
        return loop

    @staticmethod
    def __register_waiter(waiters: set[asyncio.Future[None]], loop: asyncio.AbstractEventLoop) -> asyncio.Future[None]:
        waiter: asyncio.Future[None] = loop.create_future()
        waiters.add(waiter)
        waiter.add_done_callback(waiters.discard)
        return waiter
