from __future__ import annotations

import pytest


@pytest.fixture(params=[False, True], ids=lambda p: f"debug_mode__{p}")
def debug_mode(request: pytest.FixtureRequest) -> bool:
    return bool(request.param)
