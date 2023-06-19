# -*- coding: utf-8 -*-

from __future__ import annotations

import time
from typing import Any, Generator, TypeVar, final

import pytest

_T_contra = TypeVar("_T_contra", contravariant=True)
_V_co = TypeVar("_V_co", covariant=True)


def send_return(gen: Generator[Any, _T_contra, _V_co], value: _T_contra, /) -> _V_co:
    with pytest.raises(StopIteration) as exc_info:
        gen.send(value)
    return exc_info.value.value


@final
class TimeTest:
    def __init__(self, expected_time: float, approx: float | None = None) -> None:
        assert expected_time > 0
        self.expected_time: float = expected_time
        self.approx: float | None = approx
        self.start_time: float = -1
        self._monotonic = time.monotonic

    def __enter__(self) -> TimeTest:
        if self.start_time >= 0:
            raise TypeError("Not reentrant context manager")
        self.start_time = self._monotonic()
        return self

    def __exit__(self, *args: Any) -> None:
        end_time = self._monotonic()
        assert end_time - self.start_time == pytest.approx(self.expected_time, rel=self.approx)
