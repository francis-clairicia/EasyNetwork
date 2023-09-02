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
"""Asynchronous backend engine bindings with concurrent.futures module"""

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
    """
    Wraps a :class:`concurrent.futures.Executor` instance.


    For example, this code::

        from concurrent.futures import ProcessPoolExecutor, wait

        def main() -> None:
            with ProcessPoolExecutor() as executor:
                futures = [executor.submit(pow, a, b) for a, b in [(3, 4), (12, 2), (6, 8)]]
                wait(futures)
                results = [f.result() for f in futures]

    can be converted to::

        from concurrent.futures import ProcessPoolExecutor

        async def main() -> None:
            ...

            async with AsyncExecutor(backend, ProcessPoolExecutor()) as executor:
                async with backend.create_task_group() as task_group:
                    tasks = [task_group.start_soon(executor.run, pow, a, b) for a, b in [(3, 4), (12, 2), (6, 8)]]
                results = [await t.join() for t in tasks]
    """

    __slots__ = ("__backend", "__executor", "__weakref__")

    def __init__(self, backend: AsyncBackend, executor: concurrent.futures.Executor) -> None:
        """
        Parameters:
            backend: The asynchronous backend interface.
            executor: The executor instance to wrap.
        """
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
        """Calls :meth:`shutdown`."""
        await self.shutdown()

    async def run(self, func: Callable[_P, _T], /, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        """
        Executes ``func(*args, **kwargs)`` in the executor, blocking until it is complete.

        Example::

            async with AsyncExecutor(backend, ThreadPoolExecutor(max_workers=1)) as executor:
                result = await executor.run(pow, 323, 1235)

        Parameters:
            func: A synchronous function.
            args: Positional arguments to be passed to `func`.
            kwargs: Keyword arguments to be passed to `func`.

        Raises:
            RuntimeError: if the executor is closed.
            Exception: Whatever raises ``func(*args, **kwargs)``

        Returns:
            Whatever returns ``func(*args, **kwargs)``
        """
        try:
            return await self.__backend.wait_future(self.__executor.submit(func, *args, **kwargs))
        finally:
            del func, args, kwargs

    def shutdown_nowait(self, *, cancel_futures: bool = False) -> None:
        """
        Signal the executor that it should free any resources that it is using when the currently pending futures
        are done executing.

        Calls to :meth:`AsyncExecutor.run` made after shutdown will raise :exc:`RuntimeError`.

        Parameters:
            cancel_futures: If :data:`True`, this method will cancel all pending futures that the executor
                            has not started running. Any futures that are completed or running won't be cancelled,
                            regardless of the value of `cancel_futures`.
        """
        self.__executor.shutdown(wait=False, cancel_futures=cancel_futures)

    async def shutdown(self, *, cancel_futures: bool = False) -> None:
        """
        Signal the executor that it should free any resources that it is using when the currently pending futures
        are done executing.

        Calls to :meth:`AsyncExecutor.run` made after shutdown will raise :exc:`RuntimeError`.

        This method will block until all the pending futures are done executing and
        the resources associated with the executor have been freed.

        Parameters:
            cancel_futures: If :data:`True`, this method will cancel all pending futures that the executor
                            has not started running. Any futures that are completed or running won't be cancelled,
                            regardless of the value of `cancel_futures`.
        """
        await self.__backend.run_in_thread(self.__executor.shutdown, wait=True, cancel_futures=cancel_futures)


class AsyncThreadPoolExecutor(AsyncExecutor):
    """
    :class:`AsyncExecutor` specialization for thread pools that also handle :class:`contextvars.Context`.
    """

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
        """
        Parameters:
            backend: The asynchronous backend interface.
            kwargs: see :class:`concurrent.futures.ThreadPoolExecutor` documentation.
        """
        super().__init__(backend, concurrent.futures.ThreadPoolExecutor(**kwargs))

    async def run(self, func: Callable[_P, _T], /, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        """
        Similar to :meth:`AsyncExecutor.run`, except that contexts (:class:`contextvars.Context`) are properly propagated
        to worker threads.
        """
        ctx = contextvars.copy_context()

        if _sniffio_current_async_library_cvar is not None:
            ctx.run(_sniffio_current_async_library_cvar.set, None)

        try:
            return await super().run(ctx.run, func, *args, **kwargs)  # type: ignore[arg-type]
        finally:
            del func, args, kwargs
