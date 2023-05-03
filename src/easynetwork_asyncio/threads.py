# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""asyncio engine for easynetwork.api_async
"""

from __future__ import annotations

__all__ = ["AsyncThreadPoolExecutor", "ThreadsPortal"]

import asyncio
import concurrent.futures
import contextvars
import threading
from typing import TYPE_CHECKING, Any, Callable, Coroutine, ParamSpec, TypeVar, final

from easynetwork.api_async.backend.abc import AbstractAsyncThreadPoolExecutor, AbstractThreadsPortal

if TYPE_CHECKING:
    from easynetwork_asyncio.backend import AsyncioBackend

_P = ParamSpec("_P")
_T = TypeVar("_T")


@final
class AsyncThreadPoolExecutor(AbstractAsyncThreadPoolExecutor):
    __slots__ = ("__backend", "__executor", "__shutdown_future")

    def __init__(self, backend: AsyncioBackend, max_workers: int | None = None) -> None:
        super().__init__()

        self.__backend: AsyncioBackend = backend
        self.__executor = concurrent.futures.ThreadPoolExecutor(max_workers)
        self.__shutdown_future: concurrent.futures.Future[None] | None = None

    async def run(self, __func: Callable[_P, _T], /, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        ctx = contextvars.copy_context()
        future: concurrent.futures.Future[_T] = self.__executor.submit(ctx.run, __func, *args, **kwargs)  # type: ignore[arg-type]
        return await self.__backend.wait_future(future)

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
            del shutdown_future
            thread.join()

    @staticmethod
    def __do_shutdown(
        executor: concurrent.futures.ThreadPoolExecutor,
        future: concurrent.futures.Future[None],
    ) -> None:
        try:
            executor.shutdown(wait=True)
        except BaseException as exc:  # pragma: no cover
            future.set_exception(exc)
        else:
            future.set_result(None)
        finally:
            del future

    def get_max_number_of_workers(self) -> int:
        return self.__executor._max_workers


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
