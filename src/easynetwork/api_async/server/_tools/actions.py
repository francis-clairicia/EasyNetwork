# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Asynchronous network server module"""

from __future__ import annotations

__all__ = []  # type: list[str]

import dataclasses
from typing import Generic, TypeVar

_T = TypeVar("_T")


@dataclasses.dataclass(match_args=True, slots=True)
class RequestAction(Generic[_T]):
    request: _T


@dataclasses.dataclass(match_args=True, slots=True)
class ErrorAction:
    exception: BaseException
