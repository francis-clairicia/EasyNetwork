from __future__ import annotations

__all__ = [
    "runtime_final_class",
]

from typing import TypeVar

_T_Type = TypeVar("_T_Type", bound=type)


def runtime_final_class(cls: _T_Type) -> _T_Type:
    assert isinstance(cls, type)  # nosec assert_used

    final_cls_name = cls.__qualname__

    def __init_subclass__(cls) -> None:  # type: ignore[no-untyped-def]
        raise TypeError(f"{final_cls_name} cannot be subclassed")

    __init_subclass__.__qualname__ = f"{final_cls_name}.__init_subclass__"
    __init_subclass__.__module__ = cls.__module__

    setattr(cls, "__init_subclass__", classmethod(__init_subclass__))

    return cls
