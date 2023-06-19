# -*- coding: utf-8 -*-

from __future__ import annotations

import asyncio
import math
from typing import TYPE_CHECKING, Any

from easynetwork_asyncio.tasks import Task, TimeoutHandle, timeout, timeout_at

import pytest

if TYPE_CHECKING:
    from unittest.mock import AsyncMock, MagicMock

    from pytest_mock import MockerFixture


class TestTask:
    @pytest.fixture
    @staticmethod
    def mock_asyncio_task(mocker: MockerFixture) -> AsyncMock:
        mock = mocker.NonCallableMagicMock(spec=asyncio.Task)
        mock.done.return_value = False
        mock.cancelled.return_value = False
        mock.cancel.return_value = True
        return mock

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
        assert hash(task1) == hash(task1)  # Tests cache
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
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_asyncio_task.cancel.return_value = mocker.sentinel.task_cancelled

        # Act
        task_cancelled = task.cancel()

        # Assert
        mock_asyncio_task.cancel.assert_called_once_with()
        assert task_cancelled is mocker.sentinel.task_cancelled

    @pytest.mark.asyncio
    async def test____wait____await_task(
        self,
        task: Task[Any],
        mock_asyncio_task: AsyncMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_asyncio_task.done.return_value = False
        mock_asyncio_wait: AsyncMock = mocker.patch("asyncio.wait", autospec=True)

        # Act
        await task.wait()

        # Assert
        mock_asyncio_wait.assert_awaited_once_with({mock_asyncio_task})

    @pytest.mark.asyncio
    async def test____wait____task_already_done(
        self,
        task: Task[Any],
        mock_asyncio_task: AsyncMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_asyncio_task.done.return_value = True
        mock_asyncio_wait: AsyncMock = mocker.patch("asyncio.wait", autospec=True)

        # Act
        await task.wait()

        # Assert
        mock_asyncio_wait.assert_not_called()

    @pytest.mark.asyncio
    async def test____join____await_task(
        self,
        task: Task[Any],
        mock_asyncio_task: AsyncMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_asyncio_shield: AsyncMock = mocker.patch(
            "asyncio.shield",
            new_callable=mocker.AsyncMock,
            return_value=mocker.sentinel.task_result,
        )

        # Act
        result = await task.join()

        # Assert
        mock_asyncio_shield.assert_awaited_once_with(mock_asyncio_task)
        assert result is mocker.sentinel.task_result


class TestTimeout:
    @pytest.fixture
    @staticmethod
    def mock_asyncio_timeout_handle(mocker: MockerFixture) -> MagicMock:
        mock = mocker.NonCallableMagicMock(spec=asyncio.Timeout)
        mock.__aenter__.return_value = mock
        mock.when.return_value = None
        mock.reschedule.return_value = None
        mock.expired.return_value = False
        return mock

    @pytest.fixture
    @staticmethod
    def timeout_handle(mock_asyncio_timeout_handle: MagicMock) -> TimeoutHandle:
        return TimeoutHandle(mock_asyncio_timeout_handle)

    @pytest.mark.asyncio
    async def test____timeout____schedule_timeout(self, mocker: MockerFixture, mock_asyncio_timeout_handle: MagicMock) -> None:
        # Arrange
        mock_timeout = mocker.patch("asyncio.timeout", return_value=mock_asyncio_timeout_handle)

        # Act
        async with timeout(123456789):
            pass

        # Assert
        mock_timeout.assert_called_once_with(123456789.0)
        mock_asyncio_timeout_handle.__aenter__.assert_called_once()

    @pytest.mark.asyncio
    async def test____timeout____handle_infinite(self, mocker: MockerFixture, mock_asyncio_timeout_handle: MagicMock) -> None:
        # Arrange
        mock_timeout = mocker.patch("asyncio.timeout", return_value=mock_asyncio_timeout_handle)

        # Act
        async with timeout(math.inf):
            pass

        # Assert
        mock_timeout.assert_called_once_with(None)
        mock_asyncio_timeout_handle.__aenter__.assert_called_once()

    @pytest.mark.asyncio
    async def test____timeout_at____schedule_timeout(self, mocker: MockerFixture, mock_asyncio_timeout_handle: MagicMock) -> None:
        # Arrange
        mock_timeout_at = mocker.patch("asyncio.timeout_at", return_value=mock_asyncio_timeout_handle)

        # Act
        async with timeout_at(123456789):
            pass

        # Assert
        mock_timeout_at.assert_called_once_with(123456789.0)
        mock_asyncio_timeout_handle.__aenter__.assert_called_once()

    @pytest.mark.asyncio
    async def test____timeout_at____handle_infinite(self, mocker: MockerFixture, mock_asyncio_timeout_handle: MagicMock) -> None:
        # Arrange
        mock_timeout_at = mocker.patch("asyncio.timeout_at", return_value=mock_asyncio_timeout_handle)

        # Act
        async with timeout_at(math.inf):
            pass

        # Assert
        mock_timeout_at.assert_called_once_with(None)
        mock_asyncio_timeout_handle.__aenter__.assert_called_once()

    def test____timeout_handle____when____return_deadline(
        self,
        timeout_handle: TimeoutHandle,
        mock_asyncio_timeout_handle: MagicMock,
    ) -> None:
        # Arrange
        mock_asyncio_timeout_handle.when.return_value = 123456.789

        # Act
        deadline: float = timeout_handle.when()

        # Assert
        assert deadline == 123456.789

    def test____timeout_handle____when____infinite_deadline(
        self,
        timeout_handle: TimeoutHandle,
        mock_asyncio_timeout_handle: MagicMock,
    ) -> None:
        # Arrange
        mock_asyncio_timeout_handle.when.return_value = None

        # Act
        deadline: float = timeout_handle.when()

        # Assert
        assert deadline == math.inf

    def test____timeout_handle____reschedule____set_deadline(
        self,
        timeout_handle: TimeoutHandle,
        mock_asyncio_timeout_handle: MagicMock,
    ) -> None:
        # Arrange

        # Act
        timeout_handle.reschedule(123456.789)

        # Assert
        mock_asyncio_timeout_handle.reschedule.assert_called_once_with(123456.789)

    def test____timeout_handle____reschedule____infinite_deadline(
        self,
        timeout_handle: TimeoutHandle,
        mock_asyncio_timeout_handle: MagicMock,
    ) -> None:
        # Arrange

        # Act
        timeout_handle.reschedule(math.inf)

        # Assert
        mock_asyncio_timeout_handle.reschedule.assert_called_once_with(None)

    @pytest.mark.parametrize("expected_retval", [False, True])
    def test____expired____expected_return_value(
        self,
        expected_retval: bool,
        timeout_handle: TimeoutHandle,
        mock_asyncio_timeout_handle: MagicMock,
    ) -> None:
        # Arrange
        mock_asyncio_timeout_handle.expired.return_value = expected_retval

        # Act
        expired: bool = timeout_handle.expired()

        # Assert
        assert expired is expected_retval

    def test____deadline_property____set(
        self,
        timeout_handle: TimeoutHandle,
        mock_asyncio_timeout_handle: MagicMock,
    ) -> None:
        # Arrange
        mock_asyncio_timeout_handle.when.return_value = 4

        # Act
        timeout_handle.deadline += 12

        # Assert
        mock_asyncio_timeout_handle.when.assert_called_once_with()
        mock_asyncio_timeout_handle.reschedule.assert_called_once_with(16)

    def test____deadline_property____delete(
        self,
        timeout_handle: TimeoutHandle,
        mock_asyncio_timeout_handle: MagicMock,
    ) -> None:
        # Arrange
        mock_asyncio_timeout_handle.when.return_value = 4

        # Act
        del timeout_handle.deadline

        # Assert
        mock_asyncio_timeout_handle.when.assert_not_called()
        mock_asyncio_timeout_handle.reschedule.assert_called_once_with(None)
