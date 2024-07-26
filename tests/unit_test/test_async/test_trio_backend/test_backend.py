from __future__ import annotations

from typing import TYPE_CHECKING

from easynetwork.lowlevel.api_async.backend._trio.backend import TrioBackend

import pytest

if TYPE_CHECKING:
    from unittest.mock import AsyncMock, MagicMock

    from pytest_mock import MockerFixture


@pytest.mark.feature_trio
class TestTrioBackend:
    @pytest.fixture
    @staticmethod
    def backend() -> TrioBackend:
        return TrioBackend()

    async def test____get_cancelled_exc_class____returns_trio_Cancelled(
        self,
        backend: TrioBackend,
    ) -> None:
        # Arrange
        import trio

        # Act & Assert
        assert backend.get_cancelled_exc_class() is trio.Cancelled

    async def test____current_time____use_event_loop_time(
        self,
        backend: TrioBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        import trio

        mock_current_time: MagicMock = mocker.patch("trio.current_time", side_effect=trio.current_time)

        # Act
        current_time = backend.current_time()

        # Assert
        mock_current_time.assert_called_once_with()
        assert current_time > 0

    async def test____sleep____use_trio_sleep(
        self,
        backend: TrioBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_sleep: AsyncMock = mocker.patch("trio.sleep", autospec=True)

        # Act
        await backend.sleep(123456789)

        # Assert
        mock_sleep.assert_awaited_once_with(123456789)

    async def test____get_current_task____compute_task_info(
        self,
        backend: TrioBackend,
    ) -> None:
        # Arrange
        import trio

        current_task = trio.lowlevel.current_task()

        # Act
        task_info = backend.get_current_task()

        # Assert
        assert task_info.id == id(current_task)
        assert task_info.name == current_task.name
        assert task_info.coro is current_task.coro

    async def test____getaddrinfo____use_loop_getaddrinfo(
        self,
        backend: TrioBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_trio_getaddrinfo = mocker.patch(
            "trio.socket.getaddrinfo",
            new_callable=mocker.AsyncMock,
            return_value=mocker.sentinel.addrinfo_list,
        )

        # Act
        addrinfo_list = await backend.getaddrinfo(
            host=mocker.sentinel.host,
            port=mocker.sentinel.port,
            family=mocker.sentinel.family,
            type=mocker.sentinel.type,
            proto=mocker.sentinel.proto,
            flags=mocker.sentinel.flags,
        )

        # Assert
        assert addrinfo_list is mocker.sentinel.addrinfo_list
        mock_trio_getaddrinfo.assert_awaited_once_with(
            mocker.sentinel.host,
            mocker.sentinel.port,
            family=mocker.sentinel.family,
            type=mocker.sentinel.type,
            proto=mocker.sentinel.proto,
            flags=mocker.sentinel.flags,
        )

    async def test____getnameinfo____use_loop_getnameinfo(
        self,
        backend: TrioBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_trio_getnameinfo = mocker.patch(
            "trio.socket.getnameinfo",
            new_callable=mocker.AsyncMock,
            return_value=mocker.sentinel.resolved_addr,
        )

        # Act
        resolved_addr = await backend.getnameinfo(
            sockaddr=mocker.sentinel.sockaddr,
            flags=mocker.sentinel.flags,
        )

        # Assert
        assert resolved_addr is mocker.sentinel.resolved_addr
        mock_trio_getnameinfo.assert_awaited_once_with(mocker.sentinel.sockaddr, mocker.sentinel.flags)

    async def test____create_lock____use_trio_Lock_class(
        self,
        backend: TrioBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_Lock = mocker.patch("trio.Lock", return_value=mocker.sentinel.lock)

        # Act
        lock = backend.create_lock()

        # Assert
        mock_Lock.assert_called_once_with()
        assert lock is mocker.sentinel.lock

    async def test____create_event____use_trio_Event_class(
        self,
        backend: TrioBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_Event = mocker.patch("trio.Event", return_value=mocker.sentinel.event)

        # Act
        event = backend.create_event()

        # Assert
        mock_Event.assert_called_once_with()
        assert event is mocker.sentinel.event

    @pytest.mark.parametrize(
        "use_lock",
        [
            pytest.param(False, id="None"),
            pytest.param(True, id="trio.Lock"),
        ],
    )
    async def test____create_condition_var____use_trio_Condition_class(
        self,
        use_lock: bool,
        backend: TrioBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        import trio

        mock_lock: MagicMock | None = None if not use_lock else mocker.NonCallableMagicMock(spec=trio.Lock)
        mock_Condition = mocker.patch("trio.Condition", return_value=mocker.sentinel.condition_var)

        # Act
        condition = backend.create_condition_var(mock_lock)

        # Assert
        mock_Condition.assert_called_once_with(mock_lock)
        assert condition is mocker.sentinel.condition_var

    @pytest.mark.parametrize("abandon_on_cancel", [False, True], ids=lambda p: f"abandon_on_cancel=={p}")
    async def test____run_in_thread____use_loop_run_in_executor(
        self,
        abandon_on_cancel: bool,
        backend: TrioBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        func_stub = mocker.stub()
        mock_run_in_executor = mocker.patch(
            "trio.to_thread.run_sync",
            new_callable=mocker.AsyncMock,
            return_value=mocker.sentinel.return_value,
        )

        # Act
        ret_val = await backend.run_in_thread(
            func_stub,
            mocker.sentinel.arg1,
            mocker.sentinel.arg2,
            abandon_on_cancel=abandon_on_cancel,
        )

        # Assert
        mock_run_in_executor.assert_called_once_with(
            func_stub,
            mocker.sentinel.arg1,
            mocker.sentinel.arg2,
            abandon_on_cancel=abandon_on_cancel,
        )
        func_stub.assert_not_called()
        assert ret_val is mocker.sentinel.return_value
