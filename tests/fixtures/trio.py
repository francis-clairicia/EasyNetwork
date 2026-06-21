from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

import pytest


def trio_fixture[F: Callable[..., Any]](fixture_function: F) -> F:
    try:
        import pytest_trio
    except ImportError:
        return cast(F, pytest.fixture(fixture_function))
    else:
        return pytest_trio.trio_fixture(fixture_function)
