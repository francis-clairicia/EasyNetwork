# -*- coding: utf-8 -*-

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from easynetwork.api_async.backend.abc import AbstractAsyncBackend
from easynetwork.api_async.backend.factory import AsyncBackendFactory
from easynetwork.api_async.backend.tasks import SingleTaskRunner

import pytest

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@pytest.mark.asyncio
class TestSingleTaskRunner:
    @pytest.fixture
    @staticmethod
    def backend() -> AbstractAsyncBackend:
        return AsyncBackendFactory.new("asyncio")

    async def test____run____run_task_once(
        self,
        backend: AbstractAsyncBackend,
        mocker: MockerFixture,
    ) -> None:
        coro_func = mocker.AsyncMock(spec=lambda *args, **kwargs: None, return_value=mocker.sentinel.task_result)
        runner: SingleTaskRunner[Any] = SingleTaskRunner(backend, coro_func, 1, 2, 3, arg1=1, arg2=2, arg3=3)

        result1 = await runner.run()
        result2 = await runner.run()

        assert result1 is mocker.sentinel.task_result
        assert result2 is mocker.sentinel.task_result
        coro_func.assert_awaited_once_with(1, 2, 3, arg1=1, arg2=2, arg3=3)

    async def test____run____early_cancel(
        self,
        backend: AbstractAsyncBackend,
        mocker: MockerFixture,
    ) -> None:
        coro_func = mocker.AsyncMock(spec=lambda *args, **kwargs: None, return_value=mocker.sentinel.task_result)
        runner: SingleTaskRunner[Any] = SingleTaskRunner(backend, coro_func, 1, 2, 3, arg1=1, arg2=2, arg3=3)

        assert runner.cancel()
        assert runner.cancel()  # Cancel twice does nothing

        with pytest.raises(asyncio.CancelledError):
            await runner.run()

        coro_func.assert_not_awaited()
        coro_func.assert_not_called()

    async def test____run____cancel_while_running(self, backend: AbstractAsyncBackend) -> None:
        async def coro_func(value: int) -> int:
            return await asyncio.sleep(3600, value)

        runner: SingleTaskRunner[Any] = SingleTaskRunner(backend, coro_func, 42)

        task = asyncio.create_task(runner.run())
        await asyncio.sleep(0)
        assert not task.done()

        assert runner.cancel()
        assert runner.cancel()  # Cancel twice does nothing

        with pytest.raises(asyncio.CancelledError):
            await runner.run()

        assert task.cancelled()

    async def test____run____unhandled_exceptions(
        self,
        backend: AbstractAsyncBackend,
        mocker: MockerFixture,
    ) -> None:
        my_exc = OSError()
        coro_func = mocker.AsyncMock(spec=lambda *args, **kwargs: None, side_effect=[my_exc])
        runner: SingleTaskRunner[Any] = SingleTaskRunner(backend, coro_func)

        with pytest.raises(OSError) as exc_info_run_1:
            _ = await runner.run()
        with pytest.raises(OSError) as exc_info_run_2:
            _ = await runner.run()

        assert exc_info_run_1.value is my_exc
        assert exc_info_run_2.value is my_exc
