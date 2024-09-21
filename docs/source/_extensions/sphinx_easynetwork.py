"""
Changelog:

v0.1.0: Replace private classes in shown inheritance.
v0.1.1: Fix base is not replaced if the class is generic.
v0.2.0: Log when an object does not have a docstring.
v0.2.1: Add base class to replace.
v0.3.0: Add a "See Also" section at the end of one-shot serializers docstrings.
v0.3.1 (current): Do not log "Undocumented protocol".
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, get_args, get_origin

if TYPE_CHECKING:
    from sphinx.application import Sphinx

from easynetwork.serializers.abc import AbstractIncrementalPacketSerializer, AbstractPacketSerializer
from easynetwork.servers._base import BaseAsyncNetworkServerImpl, BaseStandaloneNetworkServerImpl
from easynetwork.servers.abc import AbstractAsyncNetworkServer, AbstractNetworkServer

logger = logging.getLogger(__name__)

_SERIALIZER_COMBINATIONS_SEE_ALSO = """
.. seealso::

   :doc:`/howto/advanced/serializer_combinations`
      This class cannot be used directly with a :class:`.StreamProtocol`. This page explains possible workarounds.
"""


def _replace_base_in_place(
    klass: type,
    bases: list[type],
    base_to_replace: type,
    base_to_set_instead: Callable[[tuple[Any, ...]], Any],
) -> None:
    if issubclass(klass, base_to_replace):
        for index, base in enumerate(bases):
            if base is base_to_replace or get_origin(base) is base_to_replace:
                bases[index] = base_to_set_instead(get_args(base))


def autodoc_process_bases(app: Sphinx, name: str, obj: type, options: dict[str, Any], bases: list[type]) -> None:
    _replace_base_in_place(obj, bases, BaseAsyncNetworkServerImpl, lambda _: AbstractAsyncNetworkServer)
    _replace_base_in_place(obj, bases, BaseStandaloneNetworkServerImpl, lambda _: AbstractNetworkServer)


def _is_magic_method(name: str) -> bool:
    _, _, name = name.rpartition(".")
    return name == f"__{name[2:-2]}__"


def autodoc_process_docstring(app: Sphinx, what: str, name: str, obj: Any, options: dict[str, Any], lines: list[str]) -> None:
    if not lines and name.startswith("easynetwork.") and not _is_magic_method(name) and what not in {"typevar", "protocol"}:
        logger.warning(f"Undocumented {what}: {name}")

    match what:
        case "class":
            if issubclass(obj, AbstractPacketSerializer) and not issubclass(obj, AbstractIncrementalPacketSerializer):
                lines.extend(_SERIALIZER_COMBINATIONS_SEE_ALSO.splitlines())
        case _:
            pass


def setup(app: Sphinx) -> dict[str, Any]:
    app.setup_extension("sphinx.ext.autodoc")
    app.connect("autodoc-process-bases", autodoc_process_bases)
    app.connect("autodoc-process-docstring", autodoc_process_docstring)

    return {
        "version": "0.3.1",
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
