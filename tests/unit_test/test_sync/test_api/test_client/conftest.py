from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@pytest.fixture(autouse=True, scope="module")
def patch_lock_with_timeout(module_mocker: MockerFixture) -> None:
    from .base import dummy_lock_with_timeout

    module_mocker.patch("easynetwork.lowlevel._utils.lock_with_timeout", new=dummy_lock_with_timeout)
