# -*- coding: Utf-8 -*-

from __future__ import annotations

from typing import Any, Generator, TypeVar

import pytest

_T_contra = TypeVar("_T_contra", contravariant=True)
_V_co = TypeVar("_V_co", covariant=True)


def send_return(gen: Generator[Any, _T_contra, _V_co], value: _T_contra, /) -> _V_co:
    with pytest.raises(StopIteration) as exc_info:
        gen.send(value)
    return exc_info.value.value
