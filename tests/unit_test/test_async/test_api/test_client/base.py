from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

import pytest

from .....tools import temporary_backend
from ....base import BaseTestSocket

if TYPE_CHECKING:
    from unittest.mock import MagicMock


class BaseTestClient(BaseTestSocket):
    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_backend(mock_backend: MagicMock) -> Iterator[MagicMock]:
        with temporary_backend(mock_backend):
            yield mock_backend
