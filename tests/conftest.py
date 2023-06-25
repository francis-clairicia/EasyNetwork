# -*- coding: utf-8 -*-

from __future__ import annotations

import os
import random

random.seed(42)  # Fully deterministic random output


def pytest_report_header() -> list[str]:
    addopts: str = os.environ.get("PYTEST_ADDOPTS", "")
    if not addopts:
        return []
    return [f"PYTEST_ADDOPTS: {addopts}"]


PYTEST_PLUGINS_PACKAGE = f"{__package__}.pytest_plugins"


pytest_plugins = [
    f"{PYTEST_PLUGINS_PACKAGE}.asyncio_event_loop",
    f"{PYTEST_PLUGINS_PACKAGE}.extra_features",
    f"{PYTEST_PLUGINS_PACKAGE}.session_exit_code",
    f"{PYTEST_PLUGINS_PACKAGE}.ssl_module",
]
