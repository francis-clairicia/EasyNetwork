from __future__ import annotations

from functools import cache
from importlib import import_module
from itertools import combinations

import pytest

from ..import_utils import ALL_EASYNETWORK_MODULES, ALL_EASYNETWORK_PACKAGES


@cache
def _catch_star_imports_within_packages() -> dict[str, list[str]]:
    import ast
    import inspect

    all_packages: dict[str, list[str]] = {}
    for package_name in ALL_EASYNETWORK_PACKAGES:
        package_file = inspect.getfile(import_module(package_name))
        with open(package_file) as package_fp:
            package_source = package_fp.read()
        tree = ast.parse(package_source, package_file)
        start_import_modules: list[str] = []

        for node in tree.body:
            match node:
                case ast.ImportFrom(module=module, names=[ast.alias(name="*")], level=level):
                    module = "." * level + (module or "")
                    start_import_modules.append(module)
                case _:
                    continue

        if start_import_modules:
            all_packages[package_name] = start_import_modules

    return all_packages


class TestStarImports:
    AUTO_IMPORTED_MODULES: dict[str, list[str]] = _catch_star_imports_within_packages()

    @pytest.mark.parametrize(
        ["module_name", "imported_module_name"],
        sorted(
            (module, imported_module)
            for module, imported_module_list in AUTO_IMPORTED_MODULES.items()
            for imported_module in imported_module_list
        ),
    )
    def test____dunder_all____values_from_imported_module_retrieved_in_main_module(
        self,
        module_name: str,
        imported_module_name: str,
    ) -> None:
        # Arrange
        module = import_module(module_name)
        imported_module = import_module(imported_module_name, package=module_name)
        module_namespace = vars(module)
        try:
            __all_module__: list[str] = module.__all__
        except AttributeError:
            pytest.fail(f"{module_name!r} does not define __all__ variable")
        try:
            __all_submodule__: list[str] = imported_module.__all__
        except AttributeError:
            pytest.fail(f"{imported_module.__name__!r} does not define __all__ variable")

        # Act
        missing_names_in_declaration = set(__all_submodule__) - set(__all_module__)
        missing_names_in_namespace = set(__all_submodule__) - set(module_namespace)

        # Assert
        assert not missing_names_in_namespace
        assert not missing_names_in_declaration

    @pytest.mark.parametrize("module_name", ALL_EASYNETWORK_MODULES)
    def test____dunder_all____is_conform(self, module_name: str) -> None:
        # Arrange
        module = import_module(module_name)
        module_namespace = vars(module)
        try:
            __all_module__: list[str] = module.__all__
        except AttributeError:
            pytest.fail(f"{module_name!r} does not define __all__ variable")
        if sorted(set(__all_module__)) != sorted(__all_module__):
            pytest.fail(f"{module_name!r}: Duplicates found in __all__")

        # Act
        unknown_names = set(__all_module__) - set(module_namespace)

        # Assert
        assert not unknown_names

    @pytest.mark.parametrize("module_name", sorted(AUTO_IMPORTED_MODULES))
    def test____dunder_all____no_conflict_between_submodules(self, module_name: str) -> None:
        # Arrange

        # Act & Assert
        for imported_module_name_lhs, imported_module_name_rhs in combinations(self.AUTO_IMPORTED_MODULES[module_name], r=2):
            imported_module_lhs = import_module(imported_module_name_lhs, package=module_name)
            imported_module_rhs = import_module(imported_module_name_rhs, package=module_name)
            imported_module_all_lhs: list[str] = imported_module_lhs.__all__
            imported_module_all_rhs: list[str] = imported_module_rhs.__all__
            conflicts = set(imported_module_all_lhs) & set(imported_module_all_rhs)
            for name in conflicts:
                assert getattr(imported_module_lhs, name) is getattr(imported_module_rhs, name)
