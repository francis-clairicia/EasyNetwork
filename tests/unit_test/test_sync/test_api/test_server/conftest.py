from __future__ import annotations

import weakref
from typing import TYPE_CHECKING

from easynetwork.servers.handlers import (
    BlockingDatagramClient,
    BlockingDatagramRequestHandler,
    BlockingStreamClient,
    BlockingStreamRequestHandler,
)

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.fixture
def mock_datagram_request_handler(mocker: MockerFixture) -> MagicMock:
    return mocker.NonCallableMagicMock(spec=BlockingDatagramRequestHandler)


@pytest.fixture
def mock_stream_request_handler(mocker: MockerFixture) -> MagicMock:
    return mocker.NonCallableMagicMock(spec=BlockingStreamRequestHandler)


@pytest.fixture
def mock_datagram_client(mocker: MockerFixture) -> MagicMock:
    mock_datagram_client = mocker.NonCallableMagicMock(spec=BlockingDatagramClient)
    mock_datagram_client.is_closing.return_value = False
    mock_datagram_client.send_packet.return_value = None
    return mock_datagram_client


@pytest.fixture
def mock_stream_client(mocker: MockerFixture) -> MagicMock:
    mock_stream_client = mocker.NonCallableMagicMock(spec=BlockingStreamClient)

    mock_stream_client.is_closing.return_value = False
    mock_stream_client.send_packet.return_value = None

    mock_stream_client_ref = weakref.ref(mock_stream_client)

    def close_side_effect() -> None:
        mock_stream_client = mock_stream_client_ref()
        if mock_stream_client is None:
            return
        mock_stream_client.is_closing.return_value = True
        mock_stream_client.send_packet.side_effect = ConnectionAbortedError

    mock_stream_client.abort.side_effect = close_side_effect
    mock_stream_client.close.side_effect = close_side_effect

    return mock_stream_client
