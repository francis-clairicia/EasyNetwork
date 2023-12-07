from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

from easynetwork.lowlevel.api_async.backend.abc import AsyncBackend
from easynetwork.lowlevel.api_async.transports.abc import AsyncDatagramTransport, AsyncStreamTransport

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class FakeCancellation(BaseException):
    pass


@pytest.fixture(scope="module", autouse=True)
def __mute_socket_getaddrinfo(module_mocker: MockerFixture) -> None:
    from socket import EAI_NONAME, gaierror

    module_mocker.patch("socket.getaddrinfo", autospec=True, side_effect=gaierror(EAI_NONAME, "Name or service not known"))


@pytest.fixture(autouse=True)
def __increase_event_loop_execution_time_before_warning(event_loop: asyncio.AbstractEventLoop) -> None:
    event_loop.slow_callback_duration = 5.0


@pytest.fixture(scope="session")
def fake_cancellation_cls() -> type[BaseException]:
    return FakeCancellation


@pytest.fixture
def mock_backend(fake_cancellation_cls: type[BaseException], mocker: MockerFixture) -> MagicMock:
    from easynetwork.lowlevel.std_asyncio.tasks import TaskGroup

    from .._utils import AsyncDummyLock

    mock_backend = mocker.NonCallableMagicMock(spec=AsyncBackend)

    mock_backend.get_cancelled_exc_class.return_value = fake_cancellation_cls
    mock_backend.create_lock.side_effect = AsyncDummyLock
    mock_backend.create_event.side_effect = asyncio.Event
    mock_backend.create_task_group.side_effect = TaskGroup

    return mock_backend


@pytest.fixture
def mock_stream_socket_adapter_factory(mocker: MockerFixture) -> Callable[[], MagicMock]:
    def factory() -> MagicMock:
        mock = mocker.NonCallableMagicMock(spec=AsyncStreamTransport)

        async def sendall_fromiter(iterable_of_data: Iterable[bytes | bytearray | memoryview]) -> None:
            await AsyncStreamTransport.send_all_from_iterable(mock, iterable_of_data)

        mock.send_all_from_iterable.side_effect = sendall_fromiter

        def close_side_effect() -> None:
            mock.is_closing.return_value = True

        mock.aclose.side_effect = close_side_effect

        mock.is_closing.return_value = False
        return mock

    return factory


@pytest.fixture
def mock_stream_socket_adapter(mock_stream_socket_adapter_factory: Callable[[], MagicMock]) -> MagicMock:
    return mock_stream_socket_adapter_factory()


@pytest.fixture
def mock_datagram_socket_adapter_factory(mocker: MockerFixture) -> Callable[[], MagicMock]:
    def factory() -> MagicMock:
        mock = mocker.NonCallableMagicMock(spec=AsyncDatagramTransport)

        def close_side_effect() -> None:
            mock.is_closing.return_value = True

        mock.aclose.side_effect = close_side_effect

        mock.is_closing.return_value = False
        return mock

    return factory


@pytest.fixture
def mock_datagram_socket_adapter(mock_datagram_socket_adapter_factory: Callable[[], MagicMock]) -> MagicMock:
    return mock_datagram_socket_adapter_factory()
