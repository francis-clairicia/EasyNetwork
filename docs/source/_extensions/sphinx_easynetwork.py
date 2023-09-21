from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sphinx.application import Sphinx

from easynetwork.api_sync.server import AbstractNetworkServer
from easynetwork.api_sync.server._base import BaseStandaloneNetworkServerImpl


def _replace_base_in_place(klass: type, bases: list[type], base_to_replace: type, base_to_set_instead: type) -> None:
    if issubclass(klass, base_to_replace):
        for index, base in enumerate(bases):
            if base is base_to_replace:
                bases[index] = base_to_set_instead


def autodoc_process_bases(app: Sphinx, name: str, obj: type, options: dict[str, Any], bases: list[type]) -> None:
    _replace_base_in_place(obj, bases, BaseStandaloneNetworkServerImpl, AbstractNetworkServer)


def setup(app: Sphinx) -> dict[str, Any]:
    app.setup_extension("sphinx.ext.autodoc")
    app.connect("autodoc-process-bases", autodoc_process_bases)

    return {
        "version": "0.1",
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
