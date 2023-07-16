from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from ...base import BaseTestSocket

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class BaseTestClient(BaseTestSocket):
    @staticmethod
    def selector_timeout_after_n_calls(mock_selector_select: MagicMock, mocker: MockerFixture, nb_calls: int) -> None:
        key = mocker.sentinel.key
        mock_selector_select.side_effect = [[key] for _ in range(nb_calls)] + [[]]


@contextlib.contextmanager
def dummy_lock_with_timeout(lock: Any, timeout: float | None, *args: Any, **kwargs: Any) -> Iterator[float | None]:
    with lock:
        yield timeout
