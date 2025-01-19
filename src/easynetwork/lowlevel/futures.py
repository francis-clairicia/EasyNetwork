# Copyright 2021-2025, Francis Clairicia-Rose-Claire-Josephine
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
"""Asynchronous backend engine bindings with ``concurrent.futures`` module."""

from __future__ import annotations

__all__ = ["AsyncExecutor", "unwrap_future"]

import concurrent.futures
import contextlib
import contextvars
import functools
import threading
from collections import deque
from collections.abc import AsyncGenerator, Callable, Iterable
from types import TracebackType
from typing import Any, Generic, ParamSpec, Self, TypeVar

import sniffio

from .api_async.backend.abc import AsyncBackend
from .api_async.backend.utils import BuiltinAsyncBackendLiteral, ensure_backend

_P = ParamSpec("_P")
_T = TypeVar("_T")
_T_Executor = TypeVar("_T_Executor", bound=concurrent.futures.Executor, covariant=True)


class AsyncExecutor(Generic[_T_Executor]):
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

            async with AsyncExecutor(ProcessPoolExecutor(), handle_contexts=False) as executor:
                async with backend.create_task_group() as task_group:
                    tasks = [await task_group.start(executor.run, pow, a, b) for a, b in [(3, 4), (12, 2), (6, 8)]]
                results = [await t.join() for t in tasks]
    """

    __slots__ = ("__backend", "__executor", "__handle_contexts", "__weakref__")

    def __init__(
        self,
        executor: _T_Executor,
        backend: AsyncBackend | BuiltinAsyncBackendLiteral | None = None,
        *,
        handle_contexts: bool = True,
    ) -> None:
        """
        Parameters:
            executor: The executor instance to wrap.
            backend: The :term:`asynchronous backend interface` to use.
            handle_contexts: If :data:`True` (the default), contexts (:class:`contextvars.Context`) are properly propagated to
                             workers. Set it to :data:`False` if the executor does not support the use of contexts
                             (e.g. :class:`concurrent.futures.ProcessPoolExecutor`).
        """
        if not isinstance(executor, concurrent.futures.Executor):
            raise TypeError("Invalid executor type")

        self.__backend: AsyncBackend = ensure_backend(backend)
        self.__executor: _T_Executor = executor
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
        return await _result_or_cancel(executor.submit(func, *args, **kwargs), backend)

    def map(self, func: Callable[..., _T], *iterables: Iterable[Any]) -> AsyncGenerator[_T]:
        """
        Returns an asynchronous iterator equivalent to ``map(fn, iter)``.

        Example::

            def pow_50(x):
                return x**50

            async with AsyncExecutor(ProcessPoolExecutor(), handle_contexts=False) as executor:
                results = [result async for result in executor.map(pow_50, (1, 4, 12))]

        Parameters:
            func: A callable that will take as many arguments as there are passed `iterables`.
            iterables: iterables yielding arguments for `func`.

        Raises:
            Exception: If ``fn(*args)`` raises for any values.

        Returns:
            An asynchronous iterator equivalent to ``map(func, *iterables)`` but the calls may be evaluated out-of-order.
        """

        executor = self.__executor
        backend = self.__backend
        fs = deque(executor.submit(self._setup_func(func), *args) for args in zip(*iterables))

        async def result_iterator() -> AsyncGenerator[_T]:
            try:
                while fs:
                    yield await _result_or_cancel(fs.popleft(), backend)
            finally:
                for future in fs:
                    future.cancel()

        return result_iterator()

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
        shutdown_callback = functools.partial(self.__executor.shutdown, wait=True, cancel_futures=cancel_futures)
        await self.__backend.run_in_thread(shutdown_callback)

    def backend(self) -> AsyncBackend:
        """
        Returns:
            The backend implementation linked to this object.
        """
        return self.__backend

    def _setup_func(self, func: Callable[_P, _T]) -> Callable[_P, _T]:
        if self.__handle_contexts:
            ctx = contextvars.copy_context()
            ctx.run(sniffio.current_async_library_cvar.set, None)
            func = functools.partial(ctx.run, func)
        return func

    @property
    def wrapped(self) -> _T_Executor:
        """The wrapped :class:`~concurrent.futures.Executor` instance. Read-only attribute."""
        return self.__executor


async def unwrap_future(future: concurrent.futures.Future[_T], backend: AsyncBackend) -> _T:
    """
    Blocks until the future is done, and returns the result.

    Cancellation handling:

        * :meth:`unwrap_future` tries to cancel the given `future` (using :meth:`concurrent.futures.Future.cancel`)

            * If the future has been effectively cancelled, the cancellation request is "accepted" and propagated.

            * Otherwise, the cancellation request is "rejected": :meth:`unwrap_future` will block until `future` is done,
              and will ignore any further cancellation request.

        * A coroutine awaiting a `future` in ``running`` state (:meth:`concurrent.futures.Future.running` returns :data:`True`)
          cannot be cancelled.

    Parameters:
        future: The future object to wait for.
        backend: The :term:`asynchronous backend interface` to use.

    Raises:
        concurrent.futures.CancelledError: the future has been unexpectedly cancelled by an external code
                                           (typically :meth:`concurrent.futures.Executor.shutdown`).
        Exception: If ``future.exception()`` does not return :data:`None`, this exception is raised.

    Returns:
        Whatever returns ``future.result()``
    """
    try:
        event_loop_thread_id = threading.get_ident()
        done_event = backend.create_event()

        async with backend.create_threads_portal() as portal:

            def on_fut_done(future: concurrent.futures.Future[_T]) -> None:
                with contextlib.suppress(RuntimeError):
                    if threading.get_ident() == event_loop_thread_id:
                        done_event.set()
                    else:
                        portal.run_sync_soon(done_event.set)

            future.add_done_callback(on_fut_done)

            try:
                await done_event.wait()
            except backend.get_cancelled_exc_class():
                if future.cancel():
                    raise

                # If future.cancel() failed, that means future.set_running_or_notify_cancel() has been called
                # and set future in RUNNING state.
                # This future cannot be cancelled anymore, therefore it must be awaited.
                await backend.ignore_cancellation(done_event.wait())
            else:
                if future.cancelled():
                    # Task cancellation prevails over future cancellation
                    await backend.coro_yield()

        return future.result(timeout=0)
    finally:
        del future


async def _result_or_cancel(future: concurrent.futures.Future[_T], backend: AsyncBackend) -> _T:
    try:
        try:
            return await unwrap_future(future, backend)
        finally:
            future.cancel()
    finally:
        # Break a reference cycle with the exception in future._exception
        del future
