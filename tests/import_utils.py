from __future__ import annotations

from functools import cache
from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pkgutil import ModuleInfo


@cache
def _catch_all_easynetwork_packages_and_modules() -> list[ModuleInfo]:
    from pkgutil import walk_packages

    result: list[ModuleInfo] = []

    for module_name in ["easynetwork"]:
        module = import_module(module_name)
        module_spec = module.__spec__

        assert module_spec is not None

        module_paths = module_spec.submodule_search_locations or module.__path__

        result.extend(walk_packages(module_paths, prefix=f"{module_spec.name}."))

    return result


ALL_EASYNETWORK_PACKAGES = [info.name for info in _catch_all_easynetwork_packages_and_modules() if info.ispkg]
ALL_EASYNETWORK_MODULES = [info.name for info in _catch_all_easynetwork_packages_and_modules()]
