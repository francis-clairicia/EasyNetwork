# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""
Asynchronous client/server module
"""

from __future__ import annotations

__all__ = ["DefaultAsyncThreadPoolExecutor"]

import concurrent.futures
import contextvars
import threading
from typing import TYPE_CHECKING, Callable, ParamSpec, TypeVar, final

from ...tools._utils import transform_future_exception as _transform_future_exception
from .abc import AbstractAsyncThreadPoolExecutor
from .sniffio import current_async_library_cvar as _sniffio_current_async_library_cvar

if TYPE_CHECKING:
    from .abc import AbstractAsyncBackend

_P = ParamSpec("_P")
_T = TypeVar("_T")


@final
class DefaultAsyncThreadPoolExecutor(AbstractAsyncThreadPoolExecutor):
    __slots__ = ("__backend", "__executor", "__shutdown_future")

    def __init__(self, backend: AbstractAsyncBackend, max_workers: int | None = None) -> None:
        super().__init__()

        self.__backend: AbstractAsyncBackend = backend
        self.__executor = concurrent.futures.ThreadPoolExecutor(max_workers)
        self.__shutdown_future: concurrent.futures.Future[None] | None = None

    async def run(self, __func: Callable[_P, _T], /, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        ctx = contextvars.copy_context()

        if _sniffio_current_async_library_cvar is not None:
            ctx.run(_sniffio_current_async_library_cvar.set, None)

        future: concurrent.futures.Future[_T] = self.__executor.submit(ctx.run, __func, *args, **kwargs)  # type: ignore[arg-type]
        del __func, args, kwargs
        try:
            return await self.__backend.wait_future(future)
        finally:
            del future

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
            future.set_exception(_transform_future_exception(exc))
            if isinstance(exc, (SystemExit, KeyboardInterrupt)):
                raise
        else:
            future.set_result(None)
        finally:
            del future

    def get_max_number_of_workers(self) -> int:
        return self.__executor._max_workers
