from __future__ import annotations

import concurrent.futures
import contextvars
from typing import TYPE_CHECKING

from easynetwork.api_async.backend.futures import AsyncExecutor
from easynetwork.api_async.backend.sniffio import current_async_library_cvar

import pytest

from ...._utils import partial_eq

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

    @pytest.fixture(params=[False, True], ids=lambda p: f"handle_context=={p}")
    @staticmethod
    def executor_handle_contexts(request: pytest.FixtureRequest) -> bool:
        return getattr(request, "param")

    @pytest.fixture
    @staticmethod
    def executor(mock_backend: MagicMock, mock_stdlib_executor: MagicMock, executor_handle_contexts: bool) -> AsyncExecutor:
        return AsyncExecutor(mock_stdlib_executor, mock_backend, handle_contexts=executor_handle_contexts)

    @pytest.fixture
    @staticmethod
    def mock_context(mocker: MockerFixture) -> MagicMock:
        return mocker.NonCallableMagicMock(spec=contextvars.Context)

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_contextvars_copy_context(
        mock_context: MagicMock,
        mocker: MockerFixture,
    ) -> MagicMock:
        return mocker.patch(
            "contextvars.copy_context",
            autospec=True,
            return_value=mock_context,
        )

    async def test___dunder_init___invalid_executor(
        self,
        mock_backend: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        invalid_executor = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError):
            _ = AsyncExecutor(invalid_executor, mock_backend)

    async def test____run____submit_to_executor_and_wait(
        self,
        executor: AsyncExecutor,
        executor_handle_contexts: bool,
        mock_backend: MagicMock,
        mock_stdlib_executor: MagicMock,
        mock_context: MagicMock,
        mock_contextvars_copy_context: MagicMock,
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
        if executor_handle_contexts:
            mock_contextvars_copy_context.assert_called_once_with()
            if current_async_library_cvar is not None:
                mock_context.run.assert_called_once_with(current_async_library_cvar.set, None)
            else:
                mock_context.run.assert_not_called()
            mock_stdlib_executor.submit.assert_called_once_with(
                partial_eq(mock_context.run, func),
                mocker.sentinel.arg1,
                mocker.sentinel.arg2,
                kw1=mocker.sentinel.kw1,
                kw2=mocker.sentinel.kw2,
            )
        else:
            mock_contextvars_copy_context.assert_not_called()
            mock_context.run.assert_not_called()
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
