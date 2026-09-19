from __future__ import annotations

from typing import TYPE_CHECKING, Any

from easynetwork.lowlevel._wakeup_socketpair import WakeupSocketPair

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.fixture(autouse=True)
def dummy_lock_cls(mocker: MockerFixture) -> tuple[Any, Any]:
    from .._utils import DummyLock, DummyRLock

    lock_patch = mocker.patch("threading.Lock", new=DummyLock)
    rlock_patch = mocker.patch("threading.RLock", new=DummyRLock)
    return lock_patch, rlock_patch


@pytest.fixture
def mock_wakeup_socketpair(mocker: MockerFixture) -> MagicMock:
    return mocker.NonCallableMagicMock(name="mock_wakeup_socketpair", spec=WakeupSocketPair)
