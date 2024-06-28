from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import TYPE_CHECKING, Any

from easynetwork.lowlevel.api_async.backend._asyncio.tasks import Task, TaskUtils
from easynetwork.lowlevel.api_async.backend.abc import TaskInfo

import pytest

if TYPE_CHECKING:
    from unittest.mock import AsyncMock

    from pytest_mock import MockerFixture


class TestTask:
    @pytest.fixture
    @staticmethod
    def mock_asyncio_task(mocker: MockerFixture) -> AsyncMock:
        mock = mocker.NonCallableMagicMock(spec=asyncio.Task)
        mock.get_name.return_value = "mock_asyncio_task"
        mock.get_coro.return_value = mocker.NonCallableMagicMock(spec=Coroutine)
        mock.done.return_value = False
        mock.cancelled.return_value = False
        mock.cancel.return_value = True
        return mock

    @pytest.fixture
    @staticmethod
    def task(mock_asyncio_task: AsyncMock) -> Task[Any]:
        return Task(mock_asyncio_task)

    def test____info_property____asyncio_task_introspection(
        self,
        mock_asyncio_task: AsyncMock,
    ) -> None:
        # Arrange
        task: Task[Any] = Task(mock_asyncio_task)
        mock_asyncio_task.get_name.assert_not_called()
        mock_asyncio_task.get_coro.assert_not_called()

        # Act
        task_info = task.info

        # Assert
        assert isinstance(task_info, TaskInfo)
        assert task_info.name == "mock_asyncio_task"
        assert task_info.id == id(mock_asyncio_task)
        assert task_info.coro is mock_asyncio_task.get_coro.return_value

    def test____equality____between_two_tasks_referencing_same_asyncio_task(self, mock_asyncio_task: AsyncMock) -> None:
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


class TestTaskUtils:
    def test____current_asyncio_task____return_current_task(self) -> None:
        # Arrange
        async def main() -> None:
            assert TaskUtils.current_asyncio_task() is asyncio.current_task()

        # Act & Assert
        asyncio.run(main())

    def test____current_asyncio_task____called_from_callback(self) -> None:
        # Arrange
        async def main() -> None:
            loop = asyncio.get_running_loop()
            future: asyncio.Future[None] = loop.create_future()

            def callback() -> None:
                try:
                    _ = TaskUtils.current_asyncio_task(loop)
                    future.set_result(None)
                except BaseException as exc:
                    future.set_exception(exc)
                finally:
                    future.cancel()

            loop.call_soon(callback)

            with pytest.raises(RuntimeError, match=r"This function should be called within a task\."):
                await future

        # Act & Assert
        asyncio.run(main())

    def test____check_current_event_loop____default(self) -> None:
        # Arrange
        async def main() -> None:
            loop = asyncio.get_running_loop()
            TaskUtils.check_current_event_loop(loop)

        # Act & Assert
        asyncio.run(main())

    def test____check_current_event_loop____called_in_another_event_loop(self) -> None:
        # Arrange
        async def main() -> None:
            # Create a fake event loop
            loop = asyncio.new_event_loop()
            TaskUtils.check_current_event_loop(loop)

        # Act & Assert
        with pytest.raises(RuntimeError, match=r"^running_loop=.+ is not loop=.+$"):
            asyncio.run(main())
