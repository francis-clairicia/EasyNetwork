# -*- coding: Utf-8 -*-

from __future__ import annotations

import random

random.seed(42)  # Fully deterministic random output

import functools
import sys

import pytest


@functools.cache
def _get_package_extra_features() -> tuple[str, ...]:
    from importlib.metadata import metadata

    return tuple(metadata("easynetwork").get_all("Provides-Extra", ()))


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "feature: mark test as extra feature test")
    for name in _get_package_extra_features():
        config.addinivalue_line("markers", f"feature_{name}: run test dealing with {name!r} extra")


def _get_markers_starting_with_prefix(item: pytest.Item, prefix: str, *, remove: bool) -> set[str]:
    markers = set(mark.name for mark in item.iter_markers() if mark.name.startswith(prefix))
    if remove:
        markers = set(m.removeprefix(prefix) for m in markers)
    return markers


def _skip_if_platform_is_not_supported(item: pytest.Item) -> None:
    actual_platform = sys.platform

    # Skip with specific declared platforms
    supported_platforms = _get_markers_starting_with_prefix(item, "platform_", remove=True)
    if supported_platforms and actual_platform not in supported_platforms:
        item.add_marker(pytest.mark.skip(f"cannot run on platform {actual_platform}"))


def _auto_add_feature_marker(item: pytest.Item) -> None:
    required_features = _get_markers_starting_with_prefix(item, "feature_", remove=True)

    if required_features and item.get_closest_marker("feature") is None:
        item.add_marker(pytest.mark.feature)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        _skip_if_platform_is_not_supported(item)
        _auto_add_feature_marker(item)
