# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2022, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Iteration utility module"""

from __future__ import annotations

__all__ = ["NoStopIteration", "consumer_start", "send_return"]

import inspect
from typing import Any, Generator, TypeVar

_T_co = TypeVar("_T_co", covariant=True)
_T_contra = TypeVar("_T_contra", contravariant=True)
_V_co = TypeVar("_V_co", covariant=True)


def consumer_start(gen: Generator[_T_co, Any, Any], /) -> _T_co:
    if inspect.getgeneratorstate(gen) != "GEN_CREATED":
        raise RuntimeError("generator already started")
    try:
        return next(gen)
    except StopIteration as exc:
        raise RuntimeError("generator didn't yield") from exc


class NoStopIteration(Exception):
    def __init__(self, *args: object) -> None:
        self.value: Any = args[0] if args else None
        super().__init__(*args)


def send_return(gen: Generator[Any, _T_contra, _V_co], value: _T_contra, /) -> _V_co:
    if inspect.getgeneratorstate(gen) == "GEN_CLOSED":
        raise RuntimeError("generator closed")
    try:
        send_value = gen.send(value)
    except StopIteration as exc:
        return exc.value
    except NoStopIteration:
        raise RuntimeError("generator raises NoStopIteration") from None
    raise NoStopIteration(send_value)
