from __future__ import annotations

import weakref
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
    mock_async_datagram_client = mocker.NonCallableMagicMock(spec=AsyncDatagramClient)
    mock_async_datagram_client.is_closing.return_value = False
    mock_async_datagram_client.send_packet.return_value = None
    return mock_async_datagram_client


@pytest.fixture
def mock_async_stream_client(mocker: MockerFixture) -> MagicMock:
    mock_async_stream_client = mocker.NonCallableMagicMock(spec=AsyncStreamClient)
    mock_async_stream_client.is_closing.return_value = False
    mock_async_stream_client.send_packet.return_value = None

    mock_async_stream_client_ref = weakref.ref(mock_async_stream_client)

    def close_side_effect() -> None:
        mock_async_stream_client = mock_async_stream_client_ref()
        if mock_async_stream_client is None:
            return
        mock_async_stream_client.is_closing.return_value = True
        mock_async_stream_client.send_packet.side_effect = ConnectionAbortedError

    mock_async_stream_client.aclose.side_effect = close_side_effect
    return mock_async_stream_client
