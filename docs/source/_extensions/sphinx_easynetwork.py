"""
Changelog:

v0.1.0: Initial
v0.1.1: Fix base is not replaced if the class is generic.
v0.2.0 (current): Log when an object does not have a docstring.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, get_origin

if TYPE_CHECKING:
    from sphinx.application import Sphinx

from easynetwork.servers._base import BaseStandaloneNetworkServerImpl
from easynetwork.servers.abc import AbstractNetworkServer

logger = logging.getLogger(__name__)


def _replace_base_in_place(klass: type, bases: list[type], base_to_replace: type, base_to_set_instead: type) -> None:
    if issubclass(klass, base_to_replace):
        for index, base in enumerate(bases):
            if get_origin(base) is base_to_replace:
                bases[index] = base_to_set_instead


def autodoc_process_bases(app: Sphinx, name: str, obj: type, options: dict[str, Any], bases: list[type]) -> None:
    _replace_base_in_place(obj, bases, BaseStandaloneNetworkServerImpl, AbstractNetworkServer)


def _is_magic_method(name: str) -> bool:
    _, _, name = name.rpartition(".")
    return name == f"__{name[2:-2]}__"


def autodoc_process_docstring(app: Sphinx, what: str, name: str, obj: Any, options: dict[str, Any], lines: list[str]) -> None:
    if not lines and name.startswith("easynetwork.") and not _is_magic_method(name) and what not in {"typevar"}:
        logger.warning(f"Undocumented {what}: {name}")


def setup(app: Sphinx) -> dict[str, Any]:
    app.setup_extension("sphinx.ext.autodoc")
    app.connect("autodoc-process-bases", autodoc_process_bases)
    app.connect("autodoc-process-docstring", autodoc_process_docstring)

    return {
        "version": "0.2.0",
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
