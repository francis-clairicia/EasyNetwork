# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""
Asynchronous client/server module
"""

from __future__ import annotations

__all__ = ["AsyncThreadPoolExecutor"]

import concurrent.futures
import contextvars
import functools
import threading
from typing import Callable, ParamSpec, TypeVar, final

from .abc import AbstractAsyncBackend, AbstractAsyncThreadPoolExecutor, AbstractTask

_P = ParamSpec("_P")
_T = TypeVar("_T")
_T_co = TypeVar("_T_co", covariant=True)


@final
class ThreadPoolTask(AbstractTask[_T_co]):
    __slots__ = ("__backend", "__future")

    def __init__(self, backend: AbstractAsyncBackend, future: concurrent.futures.Future[_T_co]) -> None:
        super().__init__()

        self.__backend: AbstractAsyncBackend = backend
        self.__future: concurrent.futures.Future[_T_co] = future

    def done(self) -> bool:
        return self.__future.done()

    def cancel(self) -> bool:
        return self.__future.cancel()

    def cancelled(self) -> bool:
        return self.__future.cancelled()

    async def join(self, *, shield: bool = False) -> _T_co:
        return await self.__backend.wait_future(self.__future, shield=shield)


@final
class AsyncThreadPoolExecutor(AbstractAsyncThreadPoolExecutor):
    __slots__ = ("__backend", "__executor", "__shutdown_future")

    def __init__(self, backend: AbstractAsyncBackend, max_workers: int | None = None) -> None:
        super().__init__()

        self.__backend: AbstractAsyncBackend = backend
        self.__executor = concurrent.futures.ThreadPoolExecutor(max_workers)
        self.__shutdown_future: concurrent.futures.Future[None] | None = None

    def submit(self, __func: Callable[_P, _T], /, *args: _P.args, **kwargs: _P.kwargs) -> AbstractTask[_T]:
        ctx = contextvars.copy_context()
        func_call = functools.partial(ctx.run, __func, *args, **kwargs)
        return ThreadPoolTask(self.__backend, self.__executor.submit(func_call))  # type: ignore[arg-type]

    async def shutdown(self) -> None:
        if self.__shutdown_future is not None:
            return await self.__backend.wait_future(self.__shutdown_future)
        shutdown_future: concurrent.futures.Future[None] = concurrent.futures.Future()
        shutdown_future.set_running_or_notify_cancel()
        assert shutdown_future.running()
        thread = threading.Thread(target=self.__do_shutdown, args=(self.__executor, shutdown_future))
        thread.start()
        try:
            self.__shutdown_future = shutdown_future
            await self.__backend.wait_future(self.__shutdown_future)
        finally:
            thread.join()

    @staticmethod
    def __do_shutdown(
        executor: concurrent.futures.ThreadPoolExecutor,
        future: concurrent.futures.Future[None],
    ) -> None:
        try:
            executor.shutdown(wait=True)
        except Exception as exc:
            future.set_exception(exc)
        else:
            future.set_result(None)
        finally:
            del future

    def get_max_number_of_workers(self) -> int:
        return self.__executor._max_workers
