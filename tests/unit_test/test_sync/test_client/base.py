from __future__ import annotations

import contextlib
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING, Any

from easynetwork.tools._utils import validate_timeout_delay

from ...base import BaseTestSocket

if TYPE_CHECKING:
    from threading import Lock
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class BaseTestClient(BaseTestSocket):
    @staticmethod
    def selector_timeout_after_n_calls(mock_selector_select: MagicMock, mocker: MockerFixture, nb_calls: int) -> None:
        key = mocker.sentinel.key
        mock_selector_select.side_effect = [[key] for _ in range(nb_calls)] + [[]]

    @staticmethod
    def selector_action_during_select(
        mock_selector_select: MagicMock,
        mocker: MockerFixture,
        callback: Callable[[], Any],
    ) -> None:
        key = mocker.sentinel.key

        def selector_side_effect(timeout: float | None = None) -> list[Any]:
            callback()
            return [key]

        mock_selector_select.side_effect = selector_side_effect


@contextlib.contextmanager
def dummy_lock_with_timeout(lock: Lock, timeout: float | None, *args: Any, **kwargs: Any) -> Iterator[float | None]:
    with contextlib.ExitStack() as stack:
        if timeout is None:
            stack.enter_context(lock)
        else:
            timeout = validate_timeout_delay(timeout, positive_check=False)
            if lock.acquire(blocking=True, timeout=timeout):
                stack.push(lock)
            else:
                raise TimeoutError()
        yield timeout
