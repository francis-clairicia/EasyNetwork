from __future__ import annotations

import sys
import time
from collections.abc import Generator
from typing import Any, TypeVar, final

import pytest

_T_contra = TypeVar("_T_contra", contravariant=True)
_V_co = TypeVar("_V_co", covariant=True)


def _make_skipif_platform(platform: str) -> pytest.MarkDecorator:
    return pytest.mark.skipif(sys.platform.startswith(platform), reason=f"cannot run on platform {platform!r}")


@final
class PlatformMarkers:
    skipif_platform_win32 = _make_skipif_platform("win32")
    skipif_platform_macOS = _make_skipif_platform("darwin")
    skipif_platform_linux = _make_skipif_platform("linux")


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
        self._perf_counter = time.perf_counter

    def __enter__(self) -> TimeTest:
        if self.start_time >= 0:
            raise TypeError("Not reentrant context manager")
        self.start_time = self._perf_counter()
        return self

    def __exit__(self, exc_type: type[Exception] | None, exc_value: Exception | None, exc_tb: Any) -> None:
        end_time = self._perf_counter()
        if exc_type is not None:
            # If an exception occurred, we cannot say if this respects the execution timeout
            return
        assert self.start_time >= 0
        assert end_time - self.start_time == pytest.approx(self.expected_time, rel=self.approx)
