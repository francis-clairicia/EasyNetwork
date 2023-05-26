# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
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
from typing import Any, Callable, Coroutine, ParamSpec, TypeVar, final

from easynetwork.api_async.backend.abc import AbstractThreadsPortal

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

    def run_coroutine(self, __coro_func: Callable[_P, Coroutine[Any, Any, _T]], /, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        self.__check_running_loop()
        future = self.run_coroutine_soon(__coro_func, *args, **kwargs)
        del __coro_func, args, kwargs
        try:
            return future.result()
        finally:
            del future

    def run_coroutine_soon(
        self,
        __coro_func: Callable[_P, Coroutine[Any, Any, _T]],
        /,
        *args: _P.args,
        **kwargs: _P.kwargs,
    ) -> concurrent.futures.Future[_T]:
        ctx: contextvars.Context | None = None

        try:
            from sniffio import current_async_library_cvar
        except ImportError:
            pass
        else:
            ctx = contextvars.copy_context()
            ctx.run(current_async_library_cvar.set, "asyncio")
            del current_async_library_cvar

        coroutine = __coro_func(*args, **kwargs)
        if not inspect.iscoroutine(coroutine):  # pragma: no cover
            raise TypeError("A coroutine object is required")

        if ctx is None:
            return asyncio.run_coroutine_threadsafe(coroutine, self.__loop)
        return ctx.run(asyncio.run_coroutine_threadsafe, coroutine, self.__loop)  # type: ignore[arg-type]

    def run_sync(self, __func: Callable[_P, _T], /, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        self.__check_running_loop()
        future = self.run_sync_soon(__func, *args, **kwargs)
        del __func, args, kwargs
        try:
            return future.result()
        finally:
            del future

    def run_sync_soon(self, __func: Callable[_P, _T], /, *args: _P.args, **kwargs: _P.kwargs) -> concurrent.futures.Future[_T]:
        def callback(future: concurrent.futures.Future[_T]) -> None:
            if not future.set_running_or_notify_cancel():
                return
            try:
                result = __func(*args, **kwargs)
            except BaseException as exc:
                future.set_exception(exc)
                raise
            else:
                future.set_result(result)
            finally:
                del future

        ctx = contextvars.copy_context()

        try:
            from sniffio import current_async_library_cvar
        except ImportError:
            pass
        else:
            ctx.run(current_async_library_cvar.set, "asyncio")
            del current_async_library_cvar

        future: concurrent.futures.Future[_T] = concurrent.futures.Future()
        self.__loop.call_soon_threadsafe(callback, future, context=ctx)
        return future

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
