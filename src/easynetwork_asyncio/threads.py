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
from collections.abc import Callable, Coroutine
from typing import Any, ParamSpec, TypeVar, final

from easynetwork.api_async.backend.abc import ThreadsPortal as AbstractThreadsPortal
from easynetwork.api_async.backend.sniffio import current_async_library_cvar as _sniffio_current_async_library_cvar
from easynetwork.tools._utils import transform_future_exception as _transform_future_exception

_P = ParamSpec("_P")
_T = TypeVar("_T")


@final
class ThreadsPortal(AbstractThreadsPortal):
    __slots__ = ("__loop",)

    def __init__(self, *, loop: asyncio.AbstractEventLoop | None = None) -> None:
        super().__init__()
        if loop is None:
            loop = asyncio.get_running_loop()
        self.__loop: asyncio.AbstractEventLoop = loop

    def run_coroutine(self, coro_func: Callable[_P, Coroutine[Any, Any, _T]], /, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        self.__check_running_loop()
        future = self.__run_coroutine_soon(coro_func, *args, **kwargs)
        del coro_func, args, kwargs
        try:
            return self.__get_result(future)
        finally:
            del future

    def __run_coroutine_soon(
        self,
        coro_func: Callable[_P, Coroutine[Any, Any, _T]],
        /,
        *args: _P.args,
        **kwargs: _P.kwargs,
    ) -> concurrent.futures.Future[_T]:
        coroutine = coro_func(*args, **kwargs)
        if _sniffio_current_async_library_cvar is not None:
            ctx = contextvars.copy_context()
            ctx.run(_sniffio_current_async_library_cvar.set, "asyncio")
            return ctx.run(asyncio.run_coroutine_threadsafe, coroutine, self.__loop)  # type: ignore[arg-type]

        return asyncio.run_coroutine_threadsafe(coroutine, self.__loop)

    def run_sync(self, func: Callable[_P, _T], /, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        self.__check_running_loop()
        future = self.__run_sync_soon(func, *args, **kwargs)
        del func, args, kwargs
        try:
            return self.__get_result(future)
        finally:
            del future

    def __run_sync_soon(self, func: Callable[_P, _T], /, *args: _P.args, **kwargs: _P.kwargs) -> concurrent.futures.Future[_T]:
        def callback(future: concurrent.futures.Future[_T]) -> None:
            try:
                result = func(*args, **kwargs)
            except BaseException as exc:
                future.set_exception(_transform_future_exception(exc))
                if isinstance(exc, (SystemExit, KeyboardInterrupt)):  # pragma: no cover
                    raise
            else:
                future.set_result(result)
            finally:
                del future

        ctx = contextvars.copy_context()

        if _sniffio_current_async_library_cvar is not None:
            ctx.run(_sniffio_current_async_library_cvar.set, "asyncio")

        future: concurrent.futures.Future[_T] = concurrent.futures.Future()
        future.set_running_or_notify_cancel()

        self.__loop.call_soon_threadsafe(callback, future, context=ctx)
        return future

    @staticmethod
    def __get_result(future: concurrent.futures.Future[_T]) -> _T:
        try:
            return future.result()
        except concurrent.futures.CancelledError:
            if not future.cancelled():  # raised from future.exception()
                raise
            raise asyncio.CancelledError() from None
        finally:
            del future

    def __check_running_loop(self) -> None:
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if running_loop is self.__loop:
            raise RuntimeError("must be called in a different OS thread")

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        return self.__loop
