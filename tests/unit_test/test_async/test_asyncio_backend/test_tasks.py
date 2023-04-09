# -*- coding: Utf-8 -*-

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Iterator

from easynetwork_asyncio.tasks import Task

import pytest

if TYPE_CHECKING:
    from unittest.mock import AsyncMock

    from pytest_mock import MockerFixture


class TestTask:
    @pytest.fixture
    @staticmethod
    def mock_asyncio_task(mocker: MockerFixture) -> AsyncMock:
        class AwaitableMock(mocker.AsyncMock):  # type: ignore[misc, name-defined]
            def __await__(self) -> Iterator[Any]:
                self.await_count += 1
                return (yield from self._helper().__await__())

            async def _helper(self) -> Any:
                return self.return_value

        return AwaitableMock(spec=asyncio.Task)

    @pytest.fixture
    @staticmethod
    def task(mock_asyncio_task: AsyncMock) -> Task[Any]:
        return Task(mock_asyncio_task)

    def test_____equality____between_two_tasks_referencing_same_asyncio_task(self, mock_asyncio_task: AsyncMock) -> None:
        # Arrange
        task1: Task[Any] = Task(mock_asyncio_task)
        task2: Task[Any] = Task(mock_asyncio_task)

        # Act & Assert
        assert task1 is not task2
        assert task1 == task2
        assert not (task1 != task2)
        assert task1 != 2
        assert hash(task1) == hash(task2)

    def test____done____asyncio_task_done(
        self,
        task: Task[Any],
        mock_asyncio_task: AsyncMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_asyncio_task.done.return_value = mocker.sentinel.task_done

        # Act
        task_done = task.done()

        # Assert
        mock_asyncio_task.done.assert_called_once_with()
        assert task_done is mocker.sentinel.task_done

    def test____cancelled____asyncio_task_cancelled(
        self,
        task: Task[Any],
        mock_asyncio_task: AsyncMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_asyncio_task.cancelled.return_value = mocker.sentinel.task_cancelled

        # Act
        task_cancelled = task.cancelled()

        # Assert
        mock_asyncio_task.cancelled.assert_called_once_with()
        assert task_cancelled is mocker.sentinel.task_cancelled

    def test____cancel____cancel_asyncio_task(
        self,
        task: Task[Any],
        mock_asyncio_task: AsyncMock,
    ) -> None:
        # Arrange
        mock_asyncio_task.cancel.return_value = None

        # Act
        task.cancel()

        # Assert
        mock_asyncio_task.cancel.assert_called_once_with()

    @pytest.mark.asyncio
    async def test____join____await_task(
        self,
        task: Task[Any],
        mock_asyncio_task: AsyncMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_asyncio_task.return_value = mocker.sentinel.task_result

        # Act
        result = await task.join()

        # Assert
        mock_asyncio_task.assert_awaited_once()
        assert result is mocker.sentinel.task_result
