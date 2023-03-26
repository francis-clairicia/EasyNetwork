# -*- coding: Utf-8 -*-

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from easynetwork.async_api.backend.abc import AbstractAsyncBackend, AbstractDatagramSocketAdapter, AbstractStreamSocketAdapter

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.fixture
def mock_backend(mocker: MockerFixture) -> MagicMock:
    from .._utils import AsyncDummyLock

    mock_backend = mocker.NonCallableMagicMock(spec=AbstractAsyncBackend)

    mock_backend.create_lock = AsyncDummyLock

    return mock_backend


@pytest.fixture
def mock_stream_socket_adapter_factory(mocker: MockerFixture, mock_backend: MagicMock) -> Callable[[], MagicMock]:
    def factory() -> MagicMock:
        mock = mocker.NonCallableMagicMock(spec=AbstractStreamSocketAdapter)
        mock.is_closing.return_value = False
        mock.get_backend.return_value = mock_backend
        return mock

    return factory


@pytest.fixture
def mock_stream_socket_adapter(mock_stream_socket_adapter_factory: Callable[[], MagicMock]) -> MagicMock:
    return mock_stream_socket_adapter_factory()


@pytest.fixture
def mock_datagram_socket_adapter_factory(mocker: MockerFixture, mock_backend: MagicMock) -> Callable[[], MagicMock]:
    def factory() -> MagicMock:
        mock = mocker.NonCallableMagicMock(spec=AbstractDatagramSocketAdapter)
        mock.is_closing.return_value = False
        mock.get_backend.return_value = mock_backend
        return mock

    return factory


@pytest.fixture
def mock_datagram_socket_adapter(mock_datagram_socket_adapter_factory: Callable[[], MagicMock]) -> MagicMock:
    return mock_datagram_socket_adapter_factory()
