from __future__ import annotations

import asyncio
import concurrent.futures
import time
from collections.abc import AsyncIterator
from typing import Any

from easynetwork.lowlevel.api_async.backend.abc import AsyncBackend
from easynetwork.lowlevel.api_async.backend.utils import new_builtin_backend
from easynetwork.lowlevel.futures import AsyncExecutor, unwrap_future

import pytest
import pytest_asyncio
import sniffio


@pytest.mark.asyncio
class TestAsyncExecutor:
    @pytest.fixture
    @staticmethod
    def max_workers(request: pytest.FixtureRequest) -> int | None:
        return getattr(request, "param", None)

    @pytest_asyncio.fixture
    @staticmethod
    async def executor(max_workers: int | None) -> AsyncIterator[AsyncExecutor[concurrent.futures.Executor]]:
        async with AsyncExecutor(concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)) as executor:
            yield executor

    async def test____run____submit_and_wait(
        self,
        executor: AsyncExecutor[concurrent.futures.Executor],
    ) -> None:
        def thread_fn(value: int) -> int:
            return value

        assert await executor.run(thread_fn, 42) == 42

    async def test____run____sniffio_contextvar_reset(
        self,
        executor: AsyncExecutor[concurrent.futures.Executor],
    ) -> None:
        sniffio.current_async_library_cvar.set("asyncio")

        def callback() -> str | None:
            return sniffio.current_async_library_cvar.get()

        cvar_inner = await executor.run(callback)
        cvar_outer = sniffio.current_async_library_cvar.get()

        assert cvar_inner is None
        assert cvar_outer == "asyncio"

    async def test____map____schedule_many_calls(
        self,
        executor: AsyncExecutor[concurrent.futures.Executor],
    ) -> None:
        def thread_fn(a: int, b: int, c: int) -> tuple[int, int, int]:
            return a, b, c

        results = [v async for v in executor.map(thread_fn, (1, 2, 3), (4, 5, 6), (7, 8, 9))]

        assert results == [(1, 4, 7), (2, 5, 8), (3, 6, 9)]

    async def test____map____early_schedule(
        self,
        executor: AsyncExecutor[concurrent.futures.Executor],
    ) -> None:
        def thread_fn(delay: float) -> int:
            time.sleep(delay)
            return 42

        iterator = executor.map(thread_fn, (0.5, 0.75, 0.25))

        executor.shutdown_nowait()
        await asyncio.sleep(1)

        async with asyncio.timeout(0):
            results = [v async for v in iterator]

        assert results == [42, 42, 42]

    async def test____map____sniffio_contextvar_reset(
        self,
        executor: AsyncExecutor[concurrent.futures.Executor],
    ) -> None:

        sniffio.current_async_library_cvar.set("asyncio")

        def callback(*args: Any) -> str | None:
            return sniffio.current_async_library_cvar.get()

        cvars_inner = [v async for v in executor.map(callback, (1, 2, 3))]
        cvar_outer = sniffio.current_async_library_cvar.get()

        assert cvars_inner == [None, None, None]
        assert cvar_outer == "asyncio"

    async def test____shutdown____idempotent(
        self,
        executor: AsyncExecutor[concurrent.futures.Executor],
    ) -> None:
        await executor.shutdown()
        await executor.shutdown()

    @pytest.mark.parametrize("max_workers", [1], indirect=True, ids=lambda nb: f"max_workers=={nb}")
    async def test____shutdown____cancel_futures(
        self,
        executor: AsyncExecutor[concurrent.futures.Executor],
    ) -> None:
        busy_task = asyncio.create_task(executor.run(time.sleep, 1))

        await asyncio.sleep(0.2)
        future_cancelled_tasks = [asyncio.create_task(executor.run(time.sleep, 0.1)) for _ in range(10)]

        await asyncio.sleep(0.1)
        await executor.shutdown(cancel_futures=True)
        await asyncio.wait({busy_task})

        assert all(t.done() for t in future_cancelled_tasks)
        assert busy_task.result() is None
        assert all(isinstance(t.exception(), concurrent.futures.CancelledError) for t in future_cancelled_tasks)


@pytest.mark.asyncio
class TestUnwrapFuture:
    @pytest.fixture
    @staticmethod
    def backend() -> AsyncBackend:
        return new_builtin_backend("asyncio")

    async def test____unwrap_future____wait_until_done(
        self,
        backend: AsyncBackend,
    ) -> None:
        event_loop = asyncio.get_running_loop()
        future: concurrent.futures.Future[int] = concurrent.futures.Future()
        event_loop.call_later(0.5, future.set_result, 42)

        assert await unwrap_future(future, backend) == 42

    @pytest.mark.parametrize("future_running", [None, "before", "after"], ids=lambda state: f"future_running=={state}")
    async def test____unwrap_future____cancel_future_if_task_is_cancelled____result(
        self,
        future_running: str | None,
        backend: AsyncBackend,
    ) -> None:
        event_loop = asyncio.get_running_loop()
        future: concurrent.futures.Future[int] = concurrent.futures.Future()
        if future_running == "before":
            future.set_running_or_notify_cancel()
            assert future.running()
            event_loop.call_later(0.5, future.set_result, 42)

        task = asyncio.create_task(unwrap_future(future, backend))
        await asyncio.sleep(0.1)

        if future_running == "after":
            future.set_running_or_notify_cancel()
            assert future.running()
            event_loop.call_later(0.5, future.set_result, 42)

        for _ in range(3):
            task.cancel()
        await asyncio.wait([task])

        if future_running is not None:
            assert not future.cancelled()
            assert not task.cancelled()
            assert task.result() == 42
        else:
            assert future.cancelled()
            assert task.cancelled()

    @pytest.mark.parametrize("future_running", [None, "before", "after"], ids=lambda state: f"future_running=={state}")
    async def test____unwrap_future____cancel_future_if_task_is_cancelled____exception(
        self,
        future_running: str | None,
        backend: AsyncBackend,
    ) -> None:
        event_loop = asyncio.get_running_loop()
        expected_error = Exception("error")
        future: concurrent.futures.Future[int] = concurrent.futures.Future()
        if future_running == "before":
            future.set_running_or_notify_cancel()
            assert future.running()
            event_loop.call_later(0.5, future.set_exception, expected_error)

        task = asyncio.create_task(unwrap_future(future, backend))
        await asyncio.sleep(0.1)

        if future_running == "after":
            future.set_running_or_notify_cancel()
            assert future.running()
            event_loop.call_later(0.5, future.set_exception, expected_error)

        for _ in range(3):
            task.cancel()
        await asyncio.wait([task])

        if future_running is not None:
            assert not future.cancelled()
            assert not task.cancelled()
            assert task.exception() is expected_error
        else:
            assert future.cancelled()
            assert task.cancelled()

    async def test____unwrap_future____future_is_cancelled(
        self,
        backend: AsyncBackend,
    ) -> None:
        event_loop = asyncio.get_running_loop()
        future: concurrent.futures.Future[int] = concurrent.futures.Future()
        task = asyncio.create_task(unwrap_future(future, backend))

        event_loop.call_later(0.1, future.cancel)
        await asyncio.wait([task])

        assert not task.cancelled()
        assert type(task.exception()) is concurrent.futures.CancelledError

    async def test____unwrap_future____already_done(
        self,
        backend: AsyncBackend,
    ) -> None:
        future: concurrent.futures.Future[int] = concurrent.futures.Future()
        future.set_result(42)

        assert await unwrap_future(future, backend) == 42

    async def test____unwrap_future____already_cancelled(
        self,
        backend: AsyncBackend,
    ) -> None:
        future: concurrent.futures.Future[int] = concurrent.futures.Future()
        future.cancel()

        with pytest.raises(concurrent.futures.CancelledError):
            await unwrap_future(future, backend)

    async def test____unwrap_future____already_cancelled____task_cancelled_too(
        self,
        backend: AsyncBackend,
    ) -> None:
        event_loop = asyncio.get_running_loop()
        future: concurrent.futures.Future[int] = concurrent.futures.Future()
        future.cancel()

        task = asyncio.create_task(unwrap_future(future, backend))
        event_loop.call_soon(task.cancel)

        with pytest.raises(asyncio.CancelledError):
            await task

    async def test____unwrap_future____task_cancellation_prevails_over_future_cancellation(
        self,
        backend: AsyncBackend,
    ) -> None:
        event_loop = asyncio.get_running_loop()
        future: concurrent.futures.Future[int] = concurrent.futures.Future()

        task = asyncio.create_task(unwrap_future(future, backend))

        event_loop.call_soon(future.cancel)
        await asyncio.sleep(0)
        event_loop.call_soon(task.cancel)

        with pytest.raises(asyncio.CancelledError):
            await task

        assert task.cancelled()
