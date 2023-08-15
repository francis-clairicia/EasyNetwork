from __future__ import annotations

from typing import TYPE_CHECKING

from easynetwork.api_async.server.handler import AsyncDatagramRequestHandler, AsyncStreamRequestHandler

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
