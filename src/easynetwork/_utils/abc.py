# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2022, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Abstract classes utility module"""

from __future__ import annotations

__all__ = [
    "concreteclass",
]

from inspect import isabstract
from typing import Any, TypeVar

_TT = TypeVar("_TT", bound=type)


def concreteclass(cls: _TT) -> _TT:
    if not isinstance(cls, type):
        raise TypeError("'cls' must be a type")
    if isabstract(cls):
        abstractmethods: Any = getattr(cls, "__abstractmethods__", set())
        raise TypeError(f"{cls.__name__} is an abstract class (abstract methods: {', '.join(abstractmethods)})")
    return cls
