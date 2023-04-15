# -*- coding: Utf-8 -*-

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from easynetwork.api_async.backend.abc import (
    AbstractAsyncBackend,
    AbstractAsyncDatagramSocketAdapter,
    AbstractAsyncStreamSocketAdapter,
)

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.fixture
def mock_backend(mocker: MockerFixture) -> MagicMock:
    from easynetwork_asyncio.tasks import TaskGroup

    from .._utils import AsyncDummyLock

    mock_backend = mocker.NonCallableMagicMock(spec=AbstractAsyncBackend)

    mock_backend.create_lock = AsyncDummyLock
    mock_backend.create_task_group = TaskGroup

    return mock_backend


@pytest.fixture
def mock_stream_socket_adapter_factory(mocker: MockerFixture) -> Callable[[], MagicMock]:
    def factory() -> MagicMock:
        mock = mocker.NonCallableMagicMock(spec=AbstractAsyncStreamSocketAdapter)
        mock.is_closing.return_value = False
        return mock

    return factory


@pytest.fixture
def mock_stream_socket_adapter(mock_stream_socket_adapter_factory: Callable[[], MagicMock]) -> MagicMock:
    return mock_stream_socket_adapter_factory()


@pytest.fixture
def mock_datagram_socket_adapter_factory(mocker: MockerFixture) -> Callable[[], MagicMock]:
    def factory() -> MagicMock:
        mock = mocker.NonCallableMagicMock(spec=AbstractAsyncDatagramSocketAdapter)
        mock.is_closing.return_value = False
        return mock

    return factory


@pytest.fixture
def mock_datagram_socket_adapter(mock_datagram_socket_adapter_factory: Callable[[], MagicMock]) -> MagicMock:
    return mock_datagram_socket_adapter_factory()
