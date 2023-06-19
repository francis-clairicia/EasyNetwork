# -*- coding: utf-8 -*-

from __future__ import annotations

import asyncio
import concurrent.futures
import time
from typing import AsyncIterator

from easynetwork.api_async.backend.abc import AbstractAsyncBackend
from easynetwork.api_async.backend.factory import AsyncBackendFactory
from easynetwork.api_async.backend.futures import AsyncThreadPoolExecutor

import pytest
import pytest_asyncio


@pytest.mark.asyncio
class TestAsyncThreadPoolExecutor:
    @pytest.fixture
    @staticmethod
    def backend() -> AbstractAsyncBackend:
        return AsyncBackendFactory.new("asyncio")

    @pytest.fixture
    @staticmethod
    def max_workers(request: pytest.FixtureRequest) -> int | None:
        return getattr(request, "param", None)

    @pytest_asyncio.fixture
    @staticmethod
    async def executor(backend: AbstractAsyncBackend, max_workers: int | None) -> AsyncIterator[AsyncThreadPoolExecutor]:
        async with AsyncThreadPoolExecutor(backend, max_workers=max_workers) as executor:
            yield executor

    async def test____run____submit_and_wait(
        self,
        executor: AsyncThreadPoolExecutor,
    ) -> None:
        def thread_fn(value: int) -> int:
            return value

        assert await executor.run(thread_fn, 42) == 42

    async def test____run____ignore_cancellation(
        self,
        event_loop: asyncio.AbstractEventLoop,
        executor: AsyncThreadPoolExecutor,
    ) -> None:
        task = event_loop.create_task(executor.run(time.sleep, 0.5))

        for i in range(5):
            for _ in range(3):
                event_loop.call_later(0.1 * i, task.cancel)

        await task
        assert not task.cancelled()

    @pytest.mark.feature_sniffio
    async def test____run____sniffio_contextvar_reset(
        self,
        executor: AsyncThreadPoolExecutor,
    ) -> None:
        import sniffio

        sniffio.current_async_library_cvar.set("asyncio")

        def callback() -> str | None:
            return sniffio.current_async_library_cvar.get()

        cvar_inner = await executor.run(callback)
        cvar_outer = sniffio.current_async_library_cvar.get()

        assert cvar_inner is None
        assert cvar_outer == "asyncio"

    async def test____shutdown____idempotent(
        self,
        executor: AsyncThreadPoolExecutor,
    ) -> None:
        await executor.shutdown()
        await executor.shutdown()

    @pytest.mark.parametrize("max_workers", [1], indirect=True, ids=lambda nb: f"max_workers=={nb}")
    async def test____shutdown____cancel_futures(
        self,
        event_loop: asyncio.AbstractEventLoop,
        executor: AsyncThreadPoolExecutor,
    ) -> None:
        busy_task = event_loop.create_task(executor.run(time.sleep, 1))

        await asyncio.sleep(0.2)
        future_cancelled_tasks = [event_loop.create_task(executor.run(time.sleep, 0.1)) for _ in range(10)]

        await asyncio.sleep(0.1)
        await executor.shutdown(cancel_futures=True)

        assert busy_task.done()
        assert all(t.done() for t in future_cancelled_tasks)
        assert busy_task.result() is None
        assert all(isinstance(t.exception(), concurrent.futures.CancelledError) for t in future_cancelled_tasks)
