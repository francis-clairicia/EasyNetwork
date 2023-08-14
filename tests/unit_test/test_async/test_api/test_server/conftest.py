from __future__ import annotations

from typing import TYPE_CHECKING

from easynetwork.api_async.server.handler import AsyncBaseRequestHandler, AsyncStreamRequestHandler

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.fixture
def mock_request_handler(mocker: MockerFixture) -> MagicMock:
    return mocker.NonCallableMagicMock(spec=AsyncBaseRequestHandler)


@pytest.fixture
def mock_stream_request_handler(mocker: MockerFixture) -> MagicMock:
    return mocker.NonCallableMagicMock(spec=AsyncStreamRequestHandler)
