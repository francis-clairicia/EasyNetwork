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
        backend: AbstractAsyncBackend,
    ) -> None:
        def thread() -> int:
            return backend.run_coroutine_from_thread(asyncio.sleep, 0.5, 42)  # type: ignore[call-arg, return-value]

        assert await asyncio.to_thread(thread) == 42

    async def test____run_sync_threadsafe____run_in_event_loop(
        self,
        backend: AbstractAsyncBackend,
    ) -> None:
        def not_threadsafe_func(value: int) -> int:
            return value

        def thread() -> int:
            return backend.run_sync_threadsafe(not_threadsafe_func, 42)

        assert await asyncio.to_thread(thread) == 42
