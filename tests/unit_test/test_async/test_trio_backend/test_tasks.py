from __future__ import annotations

from collections.abc import Coroutine
from typing import TYPE_CHECKING, Any

from easynetwork.lowlevel.api_async.backend.abc import TaskInfo

import pytest

from ....tools import call_later_with_nursery

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from trio import Nursery

    from easynetwork.lowlevel.api_async.backend._trio.tasks import Task, _OutcomeCell

    from pytest_mock import MockerFixture


@pytest.mark.feature_trio(async_test_auto_mark=True)
class TestTask:
    @pytest.fixture
    @staticmethod
    def mock_trio_task(mocker: MockerFixture) -> MagicMock:
        import trio

        mock = mocker.NonCallableMagicMock(spec=trio.lowlevel.Task)
        mock.name = "mock_asyncio_task"
        mock.coro = mocker.NonCallableMagicMock(spec=Coroutine)
        return mock

    @pytest.fixture
    @staticmethod
    def mock_trio_scope(mocker: MockerFixture) -> MagicMock:
        import trio

        return mocker.NonCallableMagicMock(spec=trio.CancelScope)

    @pytest.fixture
    @staticmethod
    def outcome_cell() -> _OutcomeCell[Any]:
        from easynetwork.lowlevel.api_async.backend._trio.tasks import _OutcomeCell

        return _OutcomeCell()

    @pytest.fixture
    @staticmethod
    def task(mock_trio_task: MagicMock, mock_trio_scope: MagicMock, outcome_cell: _OutcomeCell[Any]) -> Task[Any]:
        from easynetwork.lowlevel.api_async.backend._trio.tasks import Task

        return Task(task=mock_trio_task, scope=mock_trio_scope, outcome=outcome_cell)

    @staticmethod
    async def _get_cancelled_exc() -> BaseException:
        import outcome
        import trio

        with trio.move_on_after(0):
            result = await outcome.acapture(trio.sleep_forever)

        assert isinstance(result, outcome.Error)
        return result.error.with_traceback(None)

    def test____info_property____trio_task_introspection(
        self,
        task: Task[Any],
        mock_trio_task: MagicMock,
    ) -> None:
        # Arrange

        # Act
        task_info = task.info

        # Assert
        assert isinstance(task_info, TaskInfo)
        assert task_info.name == "mock_asyncio_task"
        assert task_info.id == id(mock_trio_task)
        assert task_info.coro is mock_trio_task.coro

    def test____done____outcome_set_result(
        self,
        task: Task[Any],
        outcome_cell: _OutcomeCell[Any],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        import outcome

        assert not task.done()

        # Act
        outcome_cell.set(outcome.Value(mocker.sentinel.result))

        # Assert
        assert task.done()

    def test____done____outcome_set_error(
        self,
        task: Task[Any],
        outcome_cell: _OutcomeCell[Any],
    ) -> None:
        # Arrange
        import outcome

        assert not task.done()

        # Act
        outcome_cell.set(outcome.Error(ValueError("error")))

        # Assert
        assert task.done()

    def test____cancel____task_not_done(
        self,
        task: Task[Any],
        mock_trio_scope: MagicMock,
    ) -> None:
        # Arrange
        assert not task.done()

        # Act
        cancel_called = task.cancel()

        # Assert
        assert cancel_called
        mock_trio_scope.cancel.assert_called_once()

    def test____cancel____task_done(
        self,
        task: Task[Any],
        mock_trio_scope: MagicMock,
        outcome_cell: _OutcomeCell[Any],
    ) -> None:
        # Arrange
        import outcome

        outcome_cell.set(outcome.Value(42))
        assert task.done()

        # Act
        cancel_called = task.cancel()

        # Assert
        assert not cancel_called
        mock_trio_scope.cancel.assert_not_called()

    def test____cancelled____task_not_done(
        self,
        task: Task[Any],
    ) -> None:
        # Arrange
        assert not task.done()

        # Act
        is_cancelled = task.cancelled()

        # Assert
        assert not is_cancelled

    def test____cancelled____task_done_with_result(
        self,
        task: Task[Any],
        outcome_cell: _OutcomeCell[Any],
    ) -> None:
        # Arrange
        import outcome

        outcome_cell.set(outcome.Value(42))
        assert task.done()

        # Act
        is_cancelled = task.cancelled()

        # Assert
        assert not is_cancelled

    def test____cancelled____task_done_with_error(
        self,
        task: Task[Any],
        outcome_cell: _OutcomeCell[Any],
    ) -> None:
        # Arrange
        import outcome

        outcome_cell.set(outcome.Error(ValueError("error")))
        assert task.done()

        # Act
        is_cancelled = task.cancelled()

        # Assert
        assert not is_cancelled

    async def test____cancelled____task_done_with_trio_Cancelled_error(
        self,
        task: Task[Any],
        outcome_cell: _OutcomeCell[Any],
    ) -> None:
        # Arrange
        import outcome

        outcome_cell.set(outcome.Error(await self._get_cancelled_exc()))
        assert task.done()

        # Act
        is_cancelled = task.cancelled()

        # Assert
        assert is_cancelled

    async def test____wait____until_result(
        self,
        nursery: Nursery,
        task: Task[Any],
        outcome_cell: _OutcomeCell[Any],
    ) -> None:
        # Arrange
        import outcome
        import trio

        call_later_with_nursery(nursery, 0.5, outcome_cell.set, outcome.Value(42))

        # Act
        with trio.fail_after(2):
            await task.wait()

        # Assert
        assert task.done()

    async def test____wait____until_error(
        self,
        nursery: Nursery,
        task: Task[Any],
        outcome_cell: _OutcomeCell[Any],
    ) -> None:
        # Arrange
        import outcome
        import trio

        call_later_with_nursery(nursery, 0.5, outcome_cell.set, outcome.Error(ValueError("error")))

        # Act
        with trio.fail_after(2):
            await task.wait()

        # Assert
        assert task.done()

    async def test____wait____until_cancellation(
        self,
        nursery: Nursery,
        task: Task[Any],
        outcome_cell: _OutcomeCell[Any],
    ) -> None:
        # Arrange
        import outcome
        import trio

        call_later_with_nursery(nursery, 0.5, outcome_cell.set, outcome.Error(await self._get_cancelled_exc()))

        # Act
        with trio.fail_after(2):
            await task.wait()

        # Assert
        assert task.done()

    async def test____wait____timeout(
        self,
        nursery: Nursery,
        task: Task[Any],
        outcome_cell: _OutcomeCell[Any],
    ) -> None:
        # Arrange
        import outcome
        import trio

        call_later_with_nursery(nursery, 1, outcome_cell.set, outcome.Value(42))

        # Act
        with trio.move_on_after(0.5) as scope:
            await task.wait()

        # Assert
        assert scope.cancelled_caught
        assert not task.done()

    async def test____wait____already_done(
        self,
        task: Task[Any],
        outcome_cell: _OutcomeCell[Any],
    ) -> None:
        # Arrange
        import outcome
        import trio.testing

        outcome_cell.set(outcome.Value(42))

        # Act & Assert
        with trio.testing.assert_no_checkpoints():
            await task.wait()

    @pytest.mark.parametrize(
        "cancellable",
        [
            pytest.param(False, id="join"),
            pytest.param(True, id="join_or_cancel"),
        ],
    )
    async def test____join____until_result(
        self,
        cancellable: bool,
        nursery: Nursery,
        task: Task[Any],
        outcome_cell: _OutcomeCell[Any],
    ) -> None:
        # Arrange
        import outcome
        import trio

        call_later_with_nursery(nursery, 0.5, outcome_cell.set, outcome.Value(42))

        # Act
        value: int = 0
        with trio.fail_after(2):
            if cancellable:
                value = await task.join()
            else:
                value = await task.join_or_cancel()
                # trio.fail_after() would never see the cancellation without this.
                await trio.lowlevel.checkpoint_if_cancelled()

        # Assert
        assert value == 42

    @pytest.mark.parametrize(
        "cancellable",
        [
            pytest.param(False, id="join"),
            pytest.param(True, id="join_or_cancel"),
        ],
    )
    async def test____join____until_error(
        self,
        cancellable: bool,
        nursery: Nursery,
        task: Task[Any],
        outcome_cell: _OutcomeCell[Any],
    ) -> None:
        # Arrange
        import outcome
        import trio

        exc = ValueError("error")
        call_later_with_nursery(nursery, 0.5, outcome_cell.set, outcome.Error(exc))

        # Act
        with pytest.raises(ValueError) as exc_info:
            with trio.fail_after(2):
                if cancellable:
                    await task.join()
                else:
                    await task.join_or_cancel()
                    # trio.fail_after() would never see the cancellation without this.
                    await trio.lowlevel.checkpoint_if_cancelled()

        # Assert
        assert exc_info.value is exc

    @pytest.mark.parametrize(
        "cancellable",
        [
            pytest.param(False, id="join"),
            pytest.param(True, id="join_or_cancel"),
        ],
    )
    async def test____join____until_cancellation(
        self,
        cancellable: bool,
        nursery: Nursery,
        task: Task[Any],
        outcome_cell: _OutcomeCell[Any],
    ) -> None:
        # Arrange
        import outcome
        import trio

        exc = await self._get_cancelled_exc()
        call_later_with_nursery(nursery, 0.5, outcome_cell.set, outcome.Error(exc))

        # Act
        with pytest.raises(trio.Cancelled) as exc_info:
            with trio.fail_after(2):
                if cancellable:
                    await task.join()
                else:
                    await task.join_or_cancel()
                    # trio.fail_after() would never see the cancellation without this.
                    await trio.lowlevel.checkpoint_if_cancelled()

        # Assert
        assert exc_info.value is exc

    @pytest.mark.parametrize(
        "cancellable",
        [
            pytest.param(False, id="join"),
            pytest.param(True, id="join_or_cancel"),
        ],
    )
    async def test____join____timeout(
        self,
        cancellable: bool,
        nursery: Nursery,
        task: Task[Any],
        outcome_cell: _OutcomeCell[Any],
    ) -> None:
        # Arrange
        import outcome
        import trio

        call_later_with_nursery(nursery, 1, outcome_cell.set, outcome.Value(42))

        # Act
        value: int | None = None
        with trio.move_on_after(0.5) as scope:
            if cancellable:
                value = await task.join()
            else:
                value = await task.join_or_cancel()

        # Assert
        if cancellable:
            assert scope.cancelled_caught
            assert not task.done()
            assert value is None
        else:
            assert not scope.cancelled_caught
            assert value == 42

    @pytest.mark.parametrize(
        "cancellable",
        [
            pytest.param(False, id="join"),
            pytest.param(True, id="join_or_cancel"),
        ],
    )
    async def test____join____already_done(
        self,
        cancellable: bool,
        task: Task[Any],
        outcome_cell: _OutcomeCell[Any],
    ) -> None:
        # Arrange
        import outcome
        import trio.testing

        outcome_cell.set(outcome.Value(42))

        # Act & Assert
        value: int | None = None
        with trio.testing.assert_no_checkpoints():
            if cancellable:
                value = await task.join()
            else:
                value = await task.join_or_cancel()

        # Assert
        assert value == 42
