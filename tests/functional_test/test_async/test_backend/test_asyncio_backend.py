# -*- coding: Utf-8 -*-

from __future__ import annotations

import asyncio
from concurrent.futures import Future

from easynetwork.api_async.backend.abc import AbstractAsyncBackend
from easynetwork.api_async.backend.factory import AsyncBackendFactory

import pytest


@pytest.mark.asyncio
class TestAsyncioBackend:
    @pytest.fixture
    @staticmethod
    def backend() -> AbstractAsyncBackend:
        return AsyncBackendFactory.new("asyncio")

    async def test____sleep_forever____sleep_until_cancellation(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AbstractAsyncBackend,
    ) -> None:
        sleep_task = event_loop.create_task(backend.sleep_forever())

        event_loop.call_later(0.5, sleep_task.cancel)

        with pytest.raises(asyncio.CancelledError):
            await sleep_task

    async def test____create_task_group____task_pool(
        self,
        backend: AbstractAsyncBackend,
    ) -> None:
        async def coroutine(value: int) -> int:
            return await asyncio.sleep(0.5, value)

        async with backend.create_task_group() as tg:
            task_42 = tg.start_soon(coroutine, 42)
            task_54 = tg.start_soon(coroutine, 54)

            assert not task_42.done()
            assert not task_54.done()

        assert task_42.done()
        assert task_54.done()
        assert not task_42.cancelled()
        assert not task_54.cancelled()
        assert await task_42.join() == 42
        assert await task_54.join() == 54

        # Join several should not raise
        assert await task_42.join() == 42
        assert await task_54.join() == 54

        # Task already done cannot be cancelled
        assert not task_42.cancel()
        assert not task_54.cancel()
        assert await task_42.join() == 42
        assert await task_54.join() == 54

    async def test____create_task_group____task_cancellation(
        self,
        backend: AbstractAsyncBackend,
    ) -> None:
        async def coroutine(value: int) -> int:
            return await asyncio.sleep(0.5, value)

        async with backend.create_task_group() as tg:
            task_42 = tg.start_soon(coroutine, 42)
            task_54 = tg.start_soon(coroutine, 54)

            await asyncio.sleep(0)
            assert not task_42.done()
            assert not task_54.done()

            assert task_42.cancel()

        assert task_42.done()
        assert task_54.done()
        assert task_42.cancelled()
        assert not task_54.cancelled()
        with pytest.raises(asyncio.CancelledError):
            await task_42.join()
        assert await task_54.join() == 54

        # Tasks cannot be cancelled twice
        assert not task_42.cancel()

    async def test____wait_future____wait_until_done(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AbstractAsyncBackend,
    ) -> None:
        future: Future[int] = Future()
        event_loop.call_later(0.5, future.set_result, 42)

        assert await backend.wait_future(future) == 42

    async def test____create_threads_portal____run_coroutine_from_thread(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AbstractAsyncBackend,
    ) -> None:
        threads_portal = backend.create_threads_portal()

        async def coroutine(value: int) -> int:
            assert asyncio.get_running_loop() is event_loop
            return await asyncio.sleep(0.5, value)

        def thread() -> int:
            with pytest.raises(RuntimeError):
                asyncio.get_running_loop()
            return threads_portal.run_coroutine(coroutine, 42)

        assert await backend.run_in_thread(thread) == 42

    async def test____create_threads_portal____run_sync_from_thread_in_event_loop(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AbstractAsyncBackend,
    ) -> None:
        threads_portal = backend.create_threads_portal()

        def not_threadsafe_func(value: int) -> int:
            assert asyncio.get_running_loop() is event_loop
            return value

        assert threads_portal.run_sync(not_threadsafe_func, 42) == 42

        def thread() -> int:
            with pytest.raises(RuntimeError):
                asyncio.get_running_loop()
            return threads_portal.run_sync(not_threadsafe_func, 42)

        assert await backend.run_in_thread(thread) == 42
