# -*- coding: utf-8 -*-

from __future__ import annotations

from selectors import BaseSelector
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.fixture
def mock_selector(mocker: MockerFixture) -> MagicMock:
    mock_selector = mocker.NonCallableMagicMock(spec=BaseSelector)
    mock_selector.__enter__.return_value = mock_selector
    mock_selector.register.return_value = None
    mock_selector.select.return_value = [mocker.sentinel.key]
    return mock_selector


@pytest.fixture(autouse=True)
def mock_selector_cls(mock_selector: MagicMock, mocker: MockerFixture) -> MagicMock:
    return mocker.patch("selectors.PollSelector", return_value=mock_selector, create=True)


@pytest.fixture
def mock_selector_register(mock_selector: MagicMock) -> MagicMock:
    return mock_selector.register


@pytest.fixture
def mock_selector_select(mock_selector: MagicMock) -> MagicMock:
    return mock_selector.select
