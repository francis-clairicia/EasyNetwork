from __future__ import annotations

import pytest

use_asyncio_transport_xfail_uvloop = pytest.mark.parametrize(
    "use_asyncio_transport",
    [
        pytest.param(False, marks=pytest.mark.xfail_uvloop),
        pytest.param(True),
    ],
    ids=lambda boolean: f"use_asyncio_transport=={boolean}",
    indirect=True,
)


@pytest.fixture(params=[False, True], ids=lambda boolean: f"use_asyncio_transport=={boolean}")
def use_asyncio_transport(request: pytest.FixtureRequest) -> bool:
    return getattr(request, "param")
