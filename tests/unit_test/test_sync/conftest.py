# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@pytest.fixture(scope="package", autouse=True)
def dummy_lock_cls(package_mocker: MockerFixture) -> Any:
    from .._utils import DummyLock

    package_mocker.patch("threading.Lock", new=DummyLock)
    package_mocker.patch("threading.RLock", new=DummyLock)
    return DummyLock
