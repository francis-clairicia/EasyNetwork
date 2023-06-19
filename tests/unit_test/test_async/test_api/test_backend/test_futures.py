# -*- coding: utf-8 -*-

from __future__ import annotations

import concurrent.futures
import contextvars
from typing import TYPE_CHECKING

from easynetwork.api_async.backend.futures import AsyncExecutor, AsyncThreadPoolExecutor
from easynetwork.api_async.backend.sniffio import current_async_library_cvar

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.mark.asyncio
class TestAsyncExecutor:
    @pytest.fixture
    @staticmethod
    def mock_stdlib_executor(mocker: MockerFixture) -> MagicMock:
        executor = mocker.NonCallableMagicMock(spec=concurrent.futures.Executor)
        executor.shutdown.return_value = None
        return executor

    @pytest.fixture
    @staticmethod
    def executor(mock_backend: MagicMock, mock_stdlib_executor: MagicMock) -> AsyncExecutor:
        return AsyncExecutor(mock_backend, mock_stdlib_executor)

    async def test____run____submit_to_executor_and_wait(
        self,
        executor: AsyncExecutor,
        mock_backend: MagicMock,
        mock_stdlib_executor: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        func = mocker.stub()
        mock_stdlib_executor.submit.return_value = mocker.sentinel.future
        mock_backend.wait_future.return_value = mocker.sentinel.result

        # Act
        result = await executor.run(
            func,
            mocker.sentinel.arg1,
            mocker.sentinel.arg2,
            kw1=mocker.sentinel.kw1,
            kw2=mocker.sentinel.kw2,
        )

        # Assert
        mock_stdlib_executor.submit.assert_called_once_with(
            func,
            mocker.sentinel.arg1,
            mocker.sentinel.arg2,
            kw1=mocker.sentinel.kw1,
            kw2=mocker.sentinel.kw2,
        )
        func.assert_not_called()
        mock_backend.wait_future.assert_awaited_once_with(mocker.sentinel.future)
        assert result is mocker.sentinel.result

    async def test____shutdown_nowait____shutdown_executor(
        self,
        executor: AsyncExecutor,
        mock_stdlib_executor: MagicMock,
    ) -> None:
        # Arrange

        # Act
        executor.shutdown_nowait()

        # Assert
        mock_stdlib_executor.shutdown.assert_called_once_with(wait=False, cancel_futures=False)

    @pytest.mark.parametrize("cancel_futures", [False, True])
    async def test____shutdown_nowait____shutdown_executor____cancel_futures(
        self,
        cancel_futures: bool,
        executor: AsyncExecutor,
        mock_stdlib_executor: MagicMock,
    ) -> None:
        # Arrange

        # Act
        executor.shutdown_nowait(cancel_futures=cancel_futures)

        # Assert
        mock_stdlib_executor.shutdown.assert_called_once_with(wait=False, cancel_futures=cancel_futures)

    async def test____shutdown____shutdown_executor(
        self,
        executor: AsyncExecutor,
        mock_backend: MagicMock,
        mock_stdlib_executor: MagicMock,
    ) -> None:
        # Arrange
        mock_backend.run_in_thread.return_value = None

        # Act
        await executor.shutdown()

        # Assert
        mock_stdlib_executor.shutdown.assert_not_called()
        mock_backend.run_in_thread.assert_awaited_once_with(mock_stdlib_executor.shutdown, wait=True, cancel_futures=False)

    @pytest.mark.parametrize("cancel_futures", [False, True])
    async def test____shutdown____shutdown_executor____cancel_futures(
        self,
        cancel_futures: bool,
        executor: AsyncExecutor,
        mock_backend: MagicMock,
        mock_stdlib_executor: MagicMock,
    ) -> None:
        # Arrange
        mock_backend.run_in_thread.return_value = None

        # Act
        await executor.shutdown(cancel_futures=cancel_futures)

        # Assert
        mock_stdlib_executor.shutdown.assert_not_called()
        mock_backend.run_in_thread.assert_awaited_once_with(
            mock_stdlib_executor.shutdown,
            wait=True,
            cancel_futures=cancel_futures,
        )

    async def test____context_manager____shutdown_executor_at_end(
        self,
        executor: AsyncExecutor,
        mock_backend: MagicMock,
        mock_stdlib_executor: MagicMock,
    ) -> None:
        # Arrange
        mock_backend.run_in_thread.return_value = None

        # Act
        async with executor as _self:
            assert _self is executor
            del _self
            mock_stdlib_executor.shutdown.assert_not_called()
            mock_backend.run_in_thread.assert_not_called()

        # Assert
        mock_stdlib_executor.shutdown.assert_not_called()
        mock_backend.run_in_thread.assert_awaited_once_with(mock_stdlib_executor.shutdown, wait=True, cancel_futures=False)


@pytest.mark.asyncio
class TestAsyncThreadPoolExecutor:
    @pytest.fixture
    @staticmethod
    def mock_stdlib_executor(mocker: MockerFixture) -> MagicMock:
        executor = mocker.NonCallableMagicMock(spec=concurrent.futures.ThreadPoolExecutor)
        executor.shutdown.return_value = None
        return executor

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_stdlib_executor_cls(mocker: MockerFixture, mock_stdlib_executor: MagicMock) -> MagicMock:
        return mocker.patch("concurrent.futures.ThreadPoolExecutor", return_value=mock_stdlib_executor)

    @pytest.fixture
    @staticmethod
    def executor(mock_backend: MagicMock) -> AsyncThreadPoolExecutor:
        return AsyncThreadPoolExecutor(mock_backend)

    async def test____dunder_init____pass_kwargs_to_executor_cls(
        self,
        mock_backend: MagicMock,
        mock_stdlib_executor_cls: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        _ = AsyncThreadPoolExecutor(
            mock_backend,
            max_workers=mocker.sentinel.max_workers,
            thread_name_prefix=mocker.sentinel.thread_name_prefix,
            initializer=mocker.sentinel.initializer,
            initargs=mocker.sentinel.initargs,
        )

        # Assert
        mock_stdlib_executor_cls.assert_called_once_with(
            max_workers=mocker.sentinel.max_workers,
            thread_name_prefix=mocker.sentinel.thread_name_prefix,
            initializer=mocker.sentinel.initializer,
            initargs=mocker.sentinel.initargs,
        )

    async def test____run____submit_to_executor_and_wait(
        self,
        executor: AsyncThreadPoolExecutor,
        mock_backend: MagicMock,
        mock_stdlib_executor: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_context: MagicMock = mocker.NonCallableMagicMock(spec=contextvars.Context)
        mock_contextvars_copy_context: MagicMock = mocker.patch(
            "contextvars.copy_context",
            autospec=True,
            return_value=mock_context,
        )
        func = mocker.stub()
        mock_stdlib_executor.submit.return_value = mocker.sentinel.future
        mock_backend.wait_future.return_value = mocker.sentinel.result

        # Act
        result = await executor.run(
            func,
            mocker.sentinel.arg1,
            mocker.sentinel.arg2,
            kw1=mocker.sentinel.kw1,
            kw2=mocker.sentinel.kw2,
        )

        # Assert
        mock_contextvars_copy_context.assert_called_once_with()
        if current_async_library_cvar is not None:
            mock_context.run.assert_called_once_with(current_async_library_cvar.set, None)
        else:
            mock_context.run.assert_not_called()
        mock_stdlib_executor.submit.assert_called_once_with(
            mock_context.run,
            func,
            mocker.sentinel.arg1,
            mocker.sentinel.arg2,
            kw1=mocker.sentinel.kw1,
            kw2=mocker.sentinel.kw2,
        )
        func.assert_not_called()
        mock_backend.wait_future.assert_awaited_once_with(mocker.sentinel.future)
        assert result is mocker.sentinel.result
