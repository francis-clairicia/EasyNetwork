from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@pytest.fixture(autouse=True)
def dummy_lock_cls(mocker: MockerFixture) -> Any:
    from .._utils import DummyLock, DummyRLock

    mocker.patch("threading.Lock", new=DummyLock)
    mocker.patch("threading.RLock", new=DummyRLock)
    return DummyLock
