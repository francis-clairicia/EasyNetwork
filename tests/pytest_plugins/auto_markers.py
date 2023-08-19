from __future__ import annotations

import pathlib

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    root_tests_directory = pathlib.PurePath(__file__).parent.parent

    unit_tests_directory = root_tests_directory / "unit_test"
    functional_tests_directory = root_tests_directory / "functional_test"
    serializer_tests_directories = {
        unit_tests_directory / "test_serializers",
        functional_tests_directory / "test_serializers",
    }

    for item in items:
        fspath = pathlib.PurePath(item.fspath)

        if any(fspath.is_relative_to(p) for p in serializer_tests_directories):
            item.add_marker(pytest.mark.serializer, append=False)

        if fspath.is_relative_to(unit_tests_directory):
            item.add_marker(pytest.mark.unit, append=False)
        elif fspath.is_relative_to(functional_tests_directory):
            item.add_marker(pytest.mark.functional, append=False)
