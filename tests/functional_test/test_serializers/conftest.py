# -*- coding: utf-8 -*-

from __future__ import annotations

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    from .base import BaseTestSerializer

    for item in items:
        class_node = item.getparent(pytest.Class)
        if class_node is None:
            continue
        if issubclass(class_node.cls, BaseTestSerializer):
            item.add_marker(pytest.mark.serializer)
