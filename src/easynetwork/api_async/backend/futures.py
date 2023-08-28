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
"""
Asynchronous client/server module
"""

from __future__ import annotations

__all__ = ["AsyncExecutor", "AsyncThreadPoolExecutor"]

import concurrent.futures
import contextvars
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, ParamSpec, Self, TypeVar, overload

from .sniffio import current_async_library_cvar as _sniffio_current_async_library_cvar

if TYPE_CHECKING:
    from types import TracebackType

    from .abc import AsyncBackend

_P = ParamSpec("_P")
_T = TypeVar("_T")


class AsyncExecutor:
    __slots__ = ("__backend", "__executor", "__weakref__")

    def __init__(self, backend: AsyncBackend, executor: concurrent.futures.Executor) -> None:
        self.__backend: AsyncBackend = backend
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

    async def run(self, func: Callable[_P, _T], /, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        try:
            return await self.__backend.wait_future(self.__executor.submit(func, *args, **kwargs))
        finally:
            del func, args, kwargs

    def shutdown_nowait(self, *, cancel_futures: bool = False) -> None:
        self.__executor.shutdown(wait=False, cancel_futures=cancel_futures)

    async def shutdown(self, *, cancel_futures: bool = False) -> None:
        await self.__backend.run_in_thread(self.__executor.shutdown, wait=True, cancel_futures=cancel_futures)


class AsyncThreadPoolExecutor(AsyncExecutor):
    __slots__ = ()

    @overload
    def __init__(self, backend: AsyncBackend) -> None:
        ...

    @overload
    def __init__(
        self,
        backend: AsyncBackend,
        *,
        max_workers: int | None = ...,
        thread_name_prefix: str = ...,
        initializer: Callable[..., object] | None = ...,
        initargs: tuple[Any, ...] = ...,
        **kwargs: Any,
    ) -> None:
        ...

    def __init__(self, backend: AsyncBackend, **kwargs: Any) -> None:
        super().__init__(backend, concurrent.futures.ThreadPoolExecutor(**kwargs))

    async def run(self, func: Callable[_P, _T], /, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        ctx = contextvars.copy_context()

        if _sniffio_current_async_library_cvar is not None:
            ctx.run(_sniffio_current_async_library_cvar.set, None)

        try:
            return await super().run(ctx.run, func, *args, **kwargs)  # type: ignore[arg-type]
        finally:
            del func, args, kwargs
