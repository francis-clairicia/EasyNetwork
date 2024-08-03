from __future__ import annotations

import functools
import inspect

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


def __has_marker(item: pytest.Item, name: str) -> bool:
    return item.get_closest_marker(name) is not None


def _ensure_trio_marker_consistency(item: pytest.Function) -> None:
    if (feature_trio_marker := item.get_closest_marker("feature_trio")) is not None:
        if item.config.pluginmanager.has_plugin("trio") and not __has_marker(item, "trio"):
            auto_mark = feature_trio_marker.kwargs.get("async_test_auto_mark", False)
            if auto_mark and inspect.iscoroutinefunction(item.obj):
                item.add_marker(pytest.mark.trio)
    elif __has_marker(item, "trio"):
        item.add_marker(pytest.mark.feature_trio)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if funcitem := item.getparent(pytest.Function):
            _ensure_trio_marker_consistency(funcitem)
        _auto_add_feature_marker(item)
