# -*- coding: utf-8 -*-

from __future__ import annotations

import pathlib

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    directory = pathlib.PurePath(__file__).parent
    for item in items:
        if pathlib.PurePath(item.fspath).is_relative_to(directory):
            item.add_marker(pytest.mark.functional)
