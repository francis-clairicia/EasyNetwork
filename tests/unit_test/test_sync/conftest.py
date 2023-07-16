from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@pytest.fixture(scope="module", autouse=True)
def dummy_lock_cls(module_mocker: MockerFixture) -> Any:
    from .._utils import DummyLock

    module_mocker.patch("threading.Lock", new=DummyLock)
    module_mocker.patch("threading.RLock", new=DummyLock)
    return DummyLock
