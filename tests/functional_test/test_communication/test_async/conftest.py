from __future__ import annotations

from collections.abc import Iterator

from easynetwork.lowlevel.std_asyncio import AsyncIOBackend

import pytest

from ....tools import temporary_backend

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
def use_asyncio_transport(request: pytest.FixtureRequest) -> Iterator[bool]:
    use_asyncio_transport: bool = getattr(request, "param")

    # TODO: Do not use temporary_backend() when env variable will be implemented
    with temporary_backend(AsyncIOBackend(transport=use_asyncio_transport)):
        yield use_asyncio_transport
