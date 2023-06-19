# -*- coding: utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""
Asynchronous client/server module
"""

from __future__ import annotations

__all__ = ["AsyncExecutor", "AsyncThreadPoolExecutor"]

import concurrent.futures
import contextvars
from typing import TYPE_CHECKING, Any, Callable, ParamSpec, Self, TypeVar, overload

from .sniffio import current_async_library_cvar as _sniffio_current_async_library_cvar

if TYPE_CHECKING:
    from types import TracebackType

    from .abc import AbstractAsyncBackend

_P = ParamSpec("_P")
_T = TypeVar("_T")


class AsyncExecutor:
    __slots__ = ("__backend", "__executor", "__weakref__")

    def __init__(self, backend: AbstractAsyncBackend, executor: concurrent.futures.Executor) -> None:
        self.__backend: AbstractAsyncBackend = backend
        self.__executor: concurrent.futures.Executor = executor

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.shutdown()

    async def run(self, __func: Callable[_P, _T], /, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        try:
            return await self.__backend.wait_future(self.__executor.submit(__func, *args, **kwargs))
        finally:
            del __func, args, kwargs

    def shutdown_nowait(self, *, cancel_futures: bool = False) -> None:
        self.__executor.shutdown(wait=False, cancel_futures=cancel_futures)

    async def shutdown(self, *, cancel_futures: bool = False) -> None:
        await self.__backend.run_in_thread(self.__executor.shutdown, wait=True, cancel_futures=cancel_futures)


class AsyncThreadPoolExecutor(AsyncExecutor):
    __slots__ = ()

    @overload
    def __init__(self, backend: AbstractAsyncBackend) -> None:
        ...

    @overload
    def __init__(
        self,
        backend: AbstractAsyncBackend,
        *,
        max_workers: int | None = ...,
        thread_name_prefix: str = ...,
        initializer: Callable[..., object] | None = ...,
        initargs: tuple[Any, ...] = ...,
    ) -> None:
        ...

    def __init__(self, backend: AbstractAsyncBackend, **kwargs: Any) -> None:
        super().__init__(backend, concurrent.futures.ThreadPoolExecutor(**kwargs))

    async def run(self, __func: Callable[_P, _T], /, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        ctx = contextvars.copy_context()

        if _sniffio_current_async_library_cvar is not None:
            ctx.run(_sniffio_current_async_library_cvar.set, None)

        try:
            return await super().run(ctx.run, __func, *args, **kwargs)  # type: ignore[arg-type]
        finally:
            del __func, args, kwargs
