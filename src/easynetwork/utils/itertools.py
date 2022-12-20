# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2022, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Iteration utility module"""

from __future__ import annotations

__all__ = ["NoStopIteration", "consume", "consumer_start", "next_return", "send_return"]

import inspect
from collections import deque
from typing import Any, Generator, Iterator, TypeVar, overload

_T = TypeVar("_T")
_T_co = TypeVar("_T_co", covariant=True)
_T_contra = TypeVar("_T_contra", contravariant=True)
_V_co = TypeVar("_V_co", covariant=True)
_NO_DEFAULT: Any = object()


def consumer_start(gen: Generator[_T_co, Any, Any], /) -> _T_co:
    if inspect.getgeneratorstate(gen) != "GEN_CREATED":
        raise RuntimeError("generator already started")
    try:
        return next(gen)
    except StopIteration as exc:
        raise RuntimeError("generator didn't yield") from exc


def consume(it: Iterator[Any], /) -> None:
    deque(it, maxlen=0)  # Consume iterator at C level


class NoStopIteration(Exception):
    def __init__(self, *args: object) -> None:
        self.value: Any = args[0] if args else None
        super().__init__(*args)


@overload
def next_return(__gen: Generator[Any, None, _V_co], /) -> _V_co:
    ...


@overload
def next_return(__gen: Generator[Any, None, _V_co], __default: _T, /) -> _V_co | _T:
    ...


def next_return(gen: Generator[Any, None, Any], default: Any = _NO_DEFAULT, /) -> Any:
    if inspect.getgeneratorstate(gen) == "GEN_CLOSED":
        raise RuntimeError("generator closed")
    try:
        value = next(gen)
    except StopIteration as exc:
        return exc.value
    except NoStopIteration:
        raise RuntimeError("generator raises NoStopIteration") from None
    if default is not _NO_DEFAULT:
        return default
    raise NoStopIteration(value)


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
