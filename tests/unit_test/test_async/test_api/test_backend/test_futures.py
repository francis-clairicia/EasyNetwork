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

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_contextvars_copy_context(mocker: MockerFixture) -> MagicMock:
        return mocker.patch("contextvars.copy_context", autospec=True)

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
        mock_contextvars_copy_context: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_context: MagicMock = mocker.NonCallableMagicMock(spec=contextvars.Context)
        mock_contextvars_copy_context.return_value = mock_context
        func = mocker.stub()
        mock_future = mocker.NonCallableMagicMock(
            spec=concurrent.futures.Future,
            **{"cancel.return_value": False},
        )
        mock_stdlib_executor.submit.return_value = mock_future
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
        mock_backend.wait_future.assert_awaited_once_with(mock_future)
        mock_future.cancel.assert_called_once_with()
        assert result is mocker.sentinel.result

    @pytest.mark.parametrize("future_exception", [Exception, None])
    async def test____map____submit_to_executor_and_wait(
        self,
        executor: AsyncExecutor,
        executor_handle_contexts: bool,
        future_exception: type[BaseException] | None,
        mock_backend: MagicMock,
        mock_stdlib_executor: MagicMock,
        mock_contextvars_copy_context: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_contexts: list[MagicMock] = [mocker.NonCallableMagicMock(spec=contextvars.Context) for _ in range(3)]
        mock_futures: list[MagicMock] = [
            mocker.NonCallableMagicMock(
                spec=concurrent.futures.Future,
                **{"result.return_value": i, "cancel.return_value": False},
            )
            for i in range(3)
        ]
        mock_contextvars_copy_context.side_effect = mock_contexts
        func = mocker.stub()
        mock_stdlib_executor.submit.side_effect = mock_futures
        if future_exception is None:
            mock_backend.wait_future.side_effect = [mocker.sentinel.result_1, mocker.sentinel.result_2, mocker.sentinel.result_3]
        else:
            mock_backend.wait_future.side_effect = future_exception()
        func_args = (mocker.sentinel.arg1, mocker.sentinel.arg2, mocker.sentinel.args3)

        # Act
        if future_exception is None:
            results = [result async for result in executor.map(func, func_args)]
        else:
            results = []
            with pytest.raises(Exception) as exc_info:
                results = [result async for result in executor.map(func, func_args)]
            assert exc_info.value is mock_backend.wait_future.side_effect

        # Assert
        if executor_handle_contexts:
            assert mock_contextvars_copy_context.call_args_list == [mocker.call() for _ in range(len(mock_contexts))]
            if current_async_library_cvar is not None:
                for mock_context in mock_contexts:
                    mock_context.run.assert_called_once_with(current_async_library_cvar.set, None)
            else:
                for mock_context in mock_contexts:
                    mock_context.run.assert_not_called()
            assert mock_stdlib_executor.submit.call_args_list == [
                mocker.call(partial_eq(mock_context.run, func), arg) for mock_context, arg in zip(mock_contexts, func_args)
            ]
        else:
            mock_contextvars_copy_context.assert_not_called()
            for mock_context in mock_contexts:
                mock_context.run.assert_not_called()
            assert mock_stdlib_executor.submit.call_args_list == [mocker.call(func, arg) for arg in func_args]
        func.assert_not_called()
        if future_exception is None:
            mock_backend.wait_future.await_args_list == [mocker.call(mock_fut) for mock_fut in mock_futures]
            assert results == [mocker.sentinel.result_1, mocker.sentinel.result_2, mocker.sentinel.result_3]
        else:
            mock_backend.wait_future.await_args_list == [mocker.call(mock_futures[0])]
            assert results == []
        for mock_fut in mock_futures:
            mock_fut.cancel.assert_called_once_with()

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
