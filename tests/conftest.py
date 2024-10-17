from __future__ import annotations

import os
import random
from typing import TYPE_CHECKING

import pytest

random.seed(42)  # Fully deterministic random output


def pytest_report_header(config: pytest.Config) -> list[str]:
    headers: list[str] = []
    addopts: str = os.environ.get("PYTEST_ADDOPTS", "")
    if addopts:
        headers.append(f"PYTEST_ADDOPTS: {addopts}")
    if config.pluginmanager.has_plugin("xdist") and config.getoption("numprocesses", 0):
        headers.append(f"distribution: {config.getoption('dist', 'no')}")
    return headers


PYTEST_PLUGINS_PACKAGE = f"{__package__}.pytest_plugins"


pytest_plugins = [
    f"{PYTEST_PLUGINS_PACKAGE}.async_finalizer",
    f"{PYTEST_PLUGINS_PACKAGE}.asyncio_event_loop",
    f"{PYTEST_PLUGINS_PACKAGE}.auto_markers",
    f"{PYTEST_PLUGINS_PACKAGE}.extra_features",
    f"{PYTEST_PLUGINS_PACKAGE}.ssl_module",
    f"{PYTEST_PLUGINS_PACKAGE}.unix_sockets",
    f"{PYTEST_PLUGINS_PACKAGE}.xdist_for_vscode",
]

if TYPE_CHECKING:
    # Import pytest plugins so Pylance can suggest defined fixtures

    from .pytest_plugins import (  # noqa: F401
        async_finalizer as async_finalizer,
        asyncio_event_loop as asyncio_event_loop,
        auto_markers as auto_markers,
        extra_features as extra_features,
        ssl_module as ssl_module,
        unix_sockets as unix_sockets,
        xdist_for_vscode as xdist_for_vscode,
    )
