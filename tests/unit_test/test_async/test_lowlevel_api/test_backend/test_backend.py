from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import TYPE_CHECKING, Any, final, no_type_check

from easynetwork.lowlevel.api_async.backend._common.fair_lock import FairLock
from easynetwork.lowlevel.api_async.backend.abc import TaskInfo

import pytest

from ...._utils import partial_eq
from ._fake_backends import BaseFakeBackend

if TYPE_CHECKING:
    from unittest.mock import AsyncMock, MagicMock

    from pytest_mock import MockerFixture


@final
class MockBackend(BaseFakeBackend):
    def __init__(self, mocker: MockerFixture) -> None:
        super().__init__()
        self.mock_coro_yield: MagicMock = mocker.MagicMock(side_effect=lambda: asyncio.sleep(0))
        self.mock_current_time: MagicMock = mocker.MagicMock(return_value=123456789)
        self.mock_sleep = mocker.AsyncMock(return_value=None)
        self.mock_run_in_thread: AsyncMock = mocker.AsyncMock(side_effect=lambda func, /, *args, **options: func(*args))

    async def coro_yield(self) -> None:
        await self.mock_coro_yield()

    async def cancel_shielded_coro_yield(self) -> None:
        await self.mock_coro_yield()

    def get_cancelled_exc_class(self) -> type[BaseException]:
        return asyncio.CancelledError

    def current_time(self) -> float:
        return self.mock_current_time()

    async def sleep(self, delay: float) -> None:
        return await self.mock_sleep(delay)

    async def ignore_cancellation(self, coroutine: Awaitable[Any]) -> Any:
        return await coroutine

    @no_type_check
    async def run_in_thread(self, *args: Any, **kwargs: Any) -> Any:
        return await self.mock_run_in_thread(*args, **kwargs)


class TestTaskInfo:
    def test____equality____between_two_task_info_objects____equal(self, mocker: MockerFixture) -> None:
        # Arrange
        t1 = TaskInfo(123456, "task", mocker.sentinel.coro)
        t2 = TaskInfo(123456, "task", mocker.sentinel.coro)

        # Act & Assert
        assert t1 == t2

    def test____equality____between_two_task_info_objects____not_equal(self, mocker: MockerFixture) -> None:
        # Arrange
        t1 = TaskInfo(123456, "task", mocker.sentinel.coro)
        t2 = TaskInfo(789123, "task", mocker.sentinel.coro)

        # Act & Assert
        assert t1 != t2

    def test____equality____with_other_object____not_implemented(self, mocker: MockerFixture) -> None:
        # Arrange
        t1 = TaskInfo(123456, "task", mocker.sentinel.coro)
        t2 = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        assert t1 != t2

    def test____hash___from_id(self, mocker: MockerFixture) -> None:
        # Arrange
        t = TaskInfo(123456, "task", mocker.sentinel.coro)

        # Act & Assert
        assert hash(t) == hash(t.id)


@pytest.mark.asyncio
class TestAsyncBackend:
    @pytest.fixture
    @staticmethod
    def backend(mocker: MockerFixture) -> MockBackend:
        return MockBackend(mocker)

    async def test____sleep_until____sleep_deadline_offset(
        self,
        backend: MockBackend,
    ) -> None:
        # Arrange
        deadline: float = 234567891.05
        expected_sleep_time: float = deadline - backend.mock_current_time.return_value

        # Act
        await backend.sleep_until(deadline)

        # Assert
        backend.mock_current_time.assert_called_once_with()
        backend.mock_sleep.assert_awaited_once_with(pytest.approx(expected_sleep_time))

    async def test____sleep_until____deadline_lower_than_current_time(
        self,
        backend: MockBackend,
    ) -> None:
        # Arrange
        deadline: float = backend.mock_current_time.return_value - 220

        # Act
        await backend.sleep_until(deadline)

        # Assert
        backend.mock_current_time.assert_called_once_with()
        backend.mock_sleep.assert_awaited_once_with(0)

    async def test____getaddrinfo____run_stdlib_function_in_thread(
        self,
        backend: MockBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_getaddrinfo = mocker.patch("socket.getaddrinfo", return_value=mocker.sentinel.addrinfo_list)

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
        backend.mock_run_in_thread.assert_awaited_once_with(
            partial_eq(
                mock_getaddrinfo,
                mocker.sentinel.host,
                mocker.sentinel.port,
                family=mocker.sentinel.family,
                type=mocker.sentinel.type,
                proto=mocker.sentinel.proto,
                flags=mocker.sentinel.flags,
            ),
            abandon_on_cancel=True,
        )

    async def test____getnameinfo____run_stdlib_function_in_thread(
        self,
        backend: MockBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_getnameinfo = mocker.patch("socket.getnameinfo", return_value=mocker.sentinel.resolved_addr)

        # Act
        resolved_addr = await backend.getnameinfo(
            sockaddr=mocker.sentinel.sockaddr,
            flags=mocker.sentinel.flags,
        )

        # Assert
        assert resolved_addr is mocker.sentinel.resolved_addr
        backend.mock_run_in_thread.assert_awaited_once_with(
            partial_eq(
                mock_getnameinfo,
                mocker.sentinel.sockaddr,
                mocker.sentinel.flags,
            ),
            abandon_on_cancel=True,
        )

    async def test____create_fair_lock____returns_default_impl(
        self,
        backend: MockBackend,
    ) -> None:
        # Arrange

        # Act
        lock = backend.create_fair_lock()

        # Assert
        assert isinstance(lock, FairLock)
        assert lock._backend is backend
