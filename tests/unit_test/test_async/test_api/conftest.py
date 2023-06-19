# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import TYPE_CHECKING

from easynetwork.api_async.server.handler import AsyncClientInterface

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.fixture
def mock_async_client(mocker: MockerFixture) -> MagicMock:
    return mocker.NonCallableMagicMock(spec=AsyncClientInterface)
