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

__all__ = ["AsyncExecutor"]

import concurrent.futures
import contextvars
import functools
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, ParamSpec, Self, TypeVar

from .factory import AsyncBackendFactory
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

            async with AsyncExecutor(ProcessPoolExecutor()) as executor:
                async with backend.create_task_group() as task_group:
                    tasks = [task_group.start_soon(executor.run, pow, a, b) for a, b in [(3, 4), (12, 2), (6, 8)]]
                results = [await t.join() for t in tasks]
    """

    __slots__ = ("__backend", "__executor", "__handle_contexts", "__weakref__")

    def __init__(
        self,
        executor: concurrent.futures.Executor,
        backend: str | AsyncBackend | None = None,
        backend_kwargs: Mapping[str, Any] | None = None,
        *,
        handle_contexts: bool = False,
    ) -> None:
        """
        Parameters:
            executor: The executor instance to wrap.
            backend: the backend to use. Automatically determined otherwise.
            backend_kwargs: Keyword arguments for backend instanciation.
                            Ignored if `backend` is already an :class:`.AsyncBackend` instance.
            handle_contexts: If :data:`True`, contexts (:class:`contextvars.Context`) are properly propagated to workers.
                             Defaults to :data:`False` because not all executors support the use of contexts
                             (e.g. :class:`concurrent.futures.ProcessPoolExecutor`).
        """
        if not isinstance(executor, concurrent.futures.Executor):
            raise TypeError("Invalid executor type")

        self.__backend: AsyncBackend = AsyncBackendFactory.ensure(backend, backend_kwargs)
        self.__executor: concurrent.futures.Executor = executor
        self.__handle_contexts: bool = bool(handle_contexts)

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

            async with AsyncExecutor(ThreadPoolExecutor(max_workers=1)) as executor:
                result = await executor.run(pow, 323, 1235)

        Warning:
            Due to the current coroutine implementation, `func` should not raise a :exc:`StopIteration`.
            This can lead to unexpected (and unwanted) behavior.

        Parameters:
            func: A synchronous function.
            args: Positional arguments to be passed to `func`.
            kwargs: Keyword arguments to be passed to `func`.

        Raises:
            RuntimeError: if the executor is closed.
            concurrent.futures.CancelledError: if the executor is shutting down and pending task has been cancelled.
            Exception: Whatever raises ``func(*args, **kwargs)``.

        Returns:
            Whatever returns ``func(*args, **kwargs)``.
        """
        func = self._setup_func(func)
        executor = self.__executor
        backend = self.__backend
        return await backend.wait_future(executor.submit(func, *args, **kwargs))

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

    def _setup_func(self, func: Callable[_P, _T]) -> Callable[_P, _T]:
        if self.__handle_contexts:
            ctx = contextvars.copy_context()

            if _sniffio_current_async_library_cvar is not None:
                ctx.run(_sniffio_current_async_library_cvar.set, None)

            func = functools.partial(ctx.run, func)  # type: ignore[assignment]
        return func
