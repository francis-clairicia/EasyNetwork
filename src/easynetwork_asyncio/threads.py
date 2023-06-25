# -*- coding: utf-8 -*-
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
from typing import Any, Callable, Coroutine, ParamSpec, TypeVar, final

from easynetwork.api_async.backend.abc import AbstractThreadsPortal
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

    def run_coroutine(self, __coro_func: Callable[_P, Coroutine[Any, Any, _T]], /, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        self.__check_running_loop()
        future = self.__run_coroutine_soon(__coro_func, *args, **kwargs)
        del __coro_func, args, kwargs
        try:
            return self.__get_result(future)
        finally:
            del future

    def __run_coroutine_soon(
        self,
        __coro_func: Callable[_P, Coroutine[Any, Any, _T]],
        /,
        *args: _P.args,
        **kwargs: _P.kwargs,
    ) -> concurrent.futures.Future[_T]:
        coroutine = __coro_func(*args, **kwargs)
        if _sniffio_current_async_library_cvar is not None:
            ctx = contextvars.copy_context()
            ctx.run(_sniffio_current_async_library_cvar.set, "asyncio")
            return ctx.run(asyncio.run_coroutine_threadsafe, coroutine, self.__loop)  # type: ignore[arg-type]

        return asyncio.run_coroutine_threadsafe(coroutine, self.__loop)

    def run_sync(self, __func: Callable[_P, _T], /, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        self.__check_running_loop()
        future = self.__run_sync_soon(__func, *args, **kwargs)
        del __func, args, kwargs
        try:
            return self.__get_result(future)
        finally:
            del future

    def __run_sync_soon(self, __func: Callable[_P, _T], /, *args: _P.args, **kwargs: _P.kwargs) -> concurrent.futures.Future[_T]:
        def callback(future: concurrent.futures.Future[_T]) -> None:
            future.set_running_or_notify_cancel()
            assert future.running()
            try:
                result = __func(*args, **kwargs)
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
