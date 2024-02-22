from __future__ import annotations

from typing import TYPE_CHECKING

from easynetwork.servers.handlers import (
    AsyncDatagramClient,
    AsyncDatagramRequestHandler,
    AsyncStreamClient,
    AsyncStreamRequestHandler,
)

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.fixture
def mock_datagram_request_handler(mocker: MockerFixture) -> MagicMock:
    return mocker.NonCallableMagicMock(spec=AsyncDatagramRequestHandler)


@pytest.fixture
def mock_stream_request_handler(mocker: MockerFixture) -> MagicMock:
    return mocker.NonCallableMagicMock(spec=AsyncStreamRequestHandler)


@pytest.fixture
def mock_async_datagram_client(mocker: MockerFixture) -> MagicMock:
    return mocker.NonCallableMagicMock(spec=AsyncDatagramClient)


@pytest.fixture
def mock_async_stream_client(mocker: MockerFixture) -> MagicMock:
    return mocker.NonCallableMagicMock(spec=AsyncStreamClient)
