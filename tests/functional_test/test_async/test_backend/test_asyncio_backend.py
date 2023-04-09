# -*- coding: Utf-8 -*-

from __future__ import annotations

import asyncio
from concurrent.futures import Future

from easynetwork.api_async.backend.abc import AbstractAsyncBackend
from easynetwork.api_async.backend.factory import AsyncBackendFactory

import pytest
import pytest_asyncio


@pytest.mark.asyncio
class TestAsyncioBackend:
    @pytest_asyncio.fixture
    @staticmethod
    async def backend() -> AbstractAsyncBackend:
        return AsyncBackendFactory.new("asyncio")

    async def test____wait_future____wait_until_done(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AbstractAsyncBackend,
    ) -> None:
        future: Future[int] = Future()
        event_loop.call_later(0.5, future.set_result, 42)

        assert await backend.wait_future(future) == 42

    async def test____run_coroutine_from_thread____wait_for_coroutine(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AbstractAsyncBackend,
    ) -> None:
        async def coroutine(value: int) -> int:
            assert asyncio.get_running_loop() is event_loop
            return await asyncio.sleep(0.5, value)

        def thread() -> int:
            with pytest.raises(RuntimeError):
                asyncio.get_running_loop()
            return backend.run_coroutine_from_thread(coroutine, 42)

        assert await backend.run_in_thread(thread) == 42

    async def test____run_sync_threadsafe____run_in_event_loop(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AbstractAsyncBackend,
    ) -> None:
        def not_threadsafe_func(value: int) -> int:
            assert asyncio.get_running_loop() is event_loop
            return value

        def thread() -> int:
            with pytest.raises(RuntimeError):
                asyncio.get_running_loop()
            return backend.run_sync_threadsafe(not_threadsafe_func, 42)

        assert await backend.run_in_thread(thread) == 42
