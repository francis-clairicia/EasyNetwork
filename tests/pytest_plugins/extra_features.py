from __future__ import annotations

import functools

import pytest


@functools.cache
def _get_package_extra_features() -> frozenset[str]:
    from importlib.metadata import metadata

    return frozenset(metadata("easynetwork").get_all("Provides-Extra", ()))


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "feature: mark test as extra feature test")
    for name in _get_package_extra_features():
        config.addinivalue_line("markers", f"feature_{name}: mark test dealing with {name!r} extra")


def _auto_add_feature_marker(item: pytest.Item) -> None:
    feature_markers = {mark.name for mark in item.iter_markers() if mark.name.startswith("feature_") or mark.name == "feature"}
    if feature_markers and "feature" not in feature_markers:
        item.add_marker(pytest.mark.feature)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        _auto_add_feature_marker(item)
