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
import threading
from typing import Any, Callable, Coroutine, ParamSpec, TypeVar, final

from easynetwork.api_async.backend.abc import AbstractThreadsPortal

_P = ParamSpec("_P")
_T = TypeVar("_T")


@final
class ThreadsPortal(AbstractThreadsPortal):
    __slots__ = ("__loop",)

    def __init__(self) -> None:
        super().__init__()
        self.__loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()

    def run_coroutine(self, __coro_func: Callable[_P, Coroutine[Any, Any, _T]], /, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        if threading.get_ident() == self.parent_thread_id:
            raise RuntimeError("must be called in a different OS thread")
        future = asyncio.run_coroutine_threadsafe(__coro_func(*args, **kwargs), self.__loop)
        try:
            return future.result()
        finally:
            del future

    def run_sync(self, __func: Callable[_P, _T], /, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        if threading.get_ident() == self.parent_thread_id:
            raise RuntimeError("must be called in a different OS thread")

        def callback(future: concurrent.futures.Future[_T]) -> None:
            future.set_running_or_notify_cancel()
            assert future.running()
            try:
                result = __func(*args, **kwargs)
            except BaseException as exc:
                future.set_exception(exc)
                raise
            else:
                future.set_result(result)
            finally:
                del future

        future: concurrent.futures.Future[_T] = concurrent.futures.Future()
        self.__loop.call_soon_threadsafe(callback, future)
        try:
            return future.result()
        finally:
            del future

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        return self.__loop
