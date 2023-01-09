# -*- coding: Utf-8 -*-

from __future__ import annotations

import sys
from typing import Any, Mapping

import pytest

if sys.version_info >= (3, 11):
    import toml
else:
    import tomli as toml


def _proxify_output(output: Any) -> Any:
    from types import MappingProxyType

    match output:
        case list():
            return tuple(map(_proxify_output, output))
        case dict():
            return MappingProxyType({k: _proxify_output(v) for k, v in output.items()})
        case _:
            return output


@pytest.fixture(scope="module")
def pyproject_toml(pytestconfig: pytest.Config) -> Mapping[str, Any]:
    with open(pytestconfig.rootpath / "pyproject.toml", "rb") as file:
        return _proxify_output(toml.load(file))


def test____pyproject_toml____optional_deps_consistency(pyproject_toml: Mapping[str, Any]) -> None:
    # Arrange
    optional_deps: dict[str, tuple[str, ...]] = dict(pyproject_toml["project"]["optional-dependencies"])

    # Act
    full_extra: set[str] = set(optional_deps.pop("full"))
    other_extras: set[str] = set(dep for deps_list in optional_deps.values() for dep in deps_list)

    # Assert
    assert other_extras == full_extra
