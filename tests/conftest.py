# -*- coding: Utf-8 -*-

from __future__ import annotations

import random

random.seed(42)  # Fully deterministic random output

import sys

import pytest


def pytest_runtest_setup(item: pytest.Item) -> None:
    actual_platform = sys.platform

    # Skip with specific declared platforms
    supported_platforms = set(
        mark.name.removeprefix("platform_") for mark in item.iter_markers() if mark.name.startswith("platform_")
    )
    if supported_platforms and actual_platform not in supported_platforms:
        pytest.skip(f"cannot run on platform {actual_platform}")
