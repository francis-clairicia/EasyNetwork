from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar, cast

import pytest

_F = TypeVar("_F", bound=Callable[..., Any])


def trio_fixture(fixture_function: _F) -> _F:
    try:
        import pytest_trio
    except ImportError:
        return cast("_F", pytest.fixture(fixture_function))
    else:
        return pytest_trio.trio_fixture(fixture_function)
