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


def __should_add_trio_marker(item: pytest.Function) -> bool:
    if not inspect.iscoroutinefunction(item.obj):
        return False
    if not item.config.pluginmanager.has_plugin("trio"):
        return False
    all_markers = list(item.iter_markers_with_node("feature_trio"))
    if not all_markers:
        return False
    auto_mark_flag_per_node: dict[str, bool] = {}
    closest_node_with_marker = all_markers[0][0]
    for node, marker in all_markers:
        auto_mark_flag_per_node.setdefault(node.nodeid, False)
        auto_mark_flag_per_node[node.nodeid] |= marker.kwargs.get("async_test_auto_mark", False)
    return auto_mark_flag_per_node[closest_node_with_marker.nodeid]


def _ensure_trio_marker_consistency(item: pytest.Function) -> None:
    has_feature_marker = __has_marker(item, "feature_trio")
    has_trio_marker = __has_marker(item, "trio")
    if has_feature_marker and not has_trio_marker:
        if __should_add_trio_marker(item):
            item.add_marker(pytest.mark.trio)
    elif has_trio_marker and not has_feature_marker:
        item.add_marker(pytest.mark.feature_trio)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if funcitem := item.getparent(pytest.Function):
            _ensure_trio_marker_consistency(funcitem)
        _auto_add_feature_marker(item)
