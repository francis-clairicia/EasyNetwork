from __future__ import annotations

import os
import random
from typing import TYPE_CHECKING

random.seed(42)  # Fully deterministic random output


def pytest_report_header() -> list[str]:
    addopts: str = os.environ.get("PYTEST_ADDOPTS", "")
    if not addopts:
        return []
    return [f"PYTEST_ADDOPTS: {addopts}"]


PYTEST_PLUGINS_PACKAGE = f"{__package__}.pytest_plugins"


pytest_plugins = [
    f"{PYTEST_PLUGINS_PACKAGE}.async_finalizer",
    f"{PYTEST_PLUGINS_PACKAGE}.asyncio_event_loop",
    f"{PYTEST_PLUGINS_PACKAGE}.auto_markers",
    f"{PYTEST_PLUGINS_PACKAGE}.extra_features",
    f"{PYTEST_PLUGINS_PACKAGE}.ssl_module",
]

if TYPE_CHECKING:
    # Import pytest plugins so Pylance can suggest defined fixtures

    from .pytest_plugins import (  # noqa: F401
        async_finalizer as async_finalizer,
        asyncio_event_loop as asyncio_event_loop,
        auto_markers as auto_markers,
        extra_features as extra_features,
        ssl_module as ssl_module,
    )
