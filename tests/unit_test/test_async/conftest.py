from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

from easynetwork.lowlevel.api_async.backend._asyncio.backend import AsyncIOBackend
from easynetwork.lowlevel.api_async.backend.abc import AsyncBackend
from easynetwork.lowlevel.api_async.transports.abc import AsyncDatagramTransport, AsyncStreamTransport

import pytest

from .mock_tools import make_transport_mock

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.fixture(scope="package")
def asyncio_backend() -> AsyncIOBackend:
    return AsyncIOBackend()


class FakeCancellation(BaseException):
    pass


@pytest.fixture(autouse=True)
def __increase_event_loop_execution_time_before_warning(event_loop: asyncio.AbstractEventLoop) -> None:
    event_loop.slow_callback_duration = 5.0


@pytest.fixture(scope="session")
def fake_cancellation_cls() -> type[BaseException]:
    return FakeCancellation


@pytest.fixture
def mock_backend(fake_cancellation_cls: type[BaseException], mocker: MockerFixture) -> MagicMock:
    from easynetwork.lowlevel.api_async.backend._asyncio.tasks import CancelScope, TaskGroup

    from .._utils import AsyncDummyLock

    mock_backend = mocker.NonCallableMagicMock(spec=AsyncBackend)

    mock_backend.get_cancelled_exc_class.return_value = fake_cancellation_cls
    mock_backend.create_lock.side_effect = AsyncDummyLock
    mock_backend.create_fair_lock.side_effect = AsyncDummyLock
    mock_backend.create_event.side_effect = asyncio.Event
    mock_backend.create_task_group.side_effect = TaskGroup
    mock_backend.open_cancel_scope.side_effect = CancelScope

    return mock_backend


@pytest.fixture
def mock_stream_transport_factory(asyncio_backend: AsyncIOBackend, mocker: MockerFixture) -> Callable[[], MagicMock]:
    def factory() -> MagicMock:
        mock = make_transport_mock(mocker=mocker, spec=AsyncStreamTransport, backend=asyncio_backend)

        async def send_all_from_iterable(iterable_of_data: Iterable[bytes | bytearray | memoryview]) -> None:
            await AsyncStreamTransport.send_all_from_iterable(mock, iterable_of_data)

        mock.send_all_from_iterable.side_effect = send_all_from_iterable
        return mock

    return factory


@pytest.fixture
def mock_stream_transport(mock_stream_transport_factory: Callable[[], MagicMock]) -> MagicMock:
    return mock_stream_transport_factory()


@pytest.fixture
def mock_datagram_transport_factory(asyncio_backend: AsyncIOBackend, mocker: MockerFixture) -> Callable[[], MagicMock]:
    def factory() -> MagicMock:
        mock = make_transport_mock(mocker=mocker, spec=AsyncDatagramTransport, backend=asyncio_backend)
        return mock

    return factory


@pytest.fixture
def mock_datagram_transport(mock_datagram_transport_factory: Callable[[], MagicMock]) -> MagicMock:
    return mock_datagram_transport_factory()
