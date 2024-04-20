from __future__ import annotations

import asyncio
import contextlib
import importlib
import sys
import time
from collections.abc import Generator, Iterator
from typing import TYPE_CHECKING, Any, Literal, TypeAlias, TypeVar, assert_never, final

import pytest

if TYPE_CHECKING:
    from _typeshed import WriteableBuffer

_T_contra = TypeVar("_T_contra", contravariant=True)
_V_co = TypeVar("_V_co", covariant=True)


def _make_skipif_platform(platform: str, reason: str) -> pytest.MarkDecorator:
    return pytest.mark.skipif(sys.platform.startswith(platform), reason=reason)


@final
class PlatformMarkers:
    @staticmethod
    def skipif_platform_win32_because(reason: str) -> pytest.MarkDecorator:
        return _make_skipif_platform("win32", reason)

    @staticmethod
    def skipif_platform_macOS_because(reason: str) -> pytest.MarkDecorator:
        return _make_skipif_platform("darwin", reason)

    @staticmethod
    def skipif_platform_linux_because(reason: str) -> pytest.MarkDecorator:
        return _make_skipif_platform("linux", reason)

    skipif_platform_win32 = skipif_platform_win32_because("cannot run on Windows")
    skipif_platform_macOS = skipif_platform_macOS_because("cannot run on MacOS")
    skipif_platform_linux = skipif_platform_linux_because("cannot run on Linux")


def send_return(gen: Generator[Any, _T_contra, _V_co], value: _T_contra, /) -> _V_co:
    with pytest.raises(StopIteration) as exc_info:
        gen.send(value)
    return exc_info.value.value


def next_return(gen: Generator[Any, Any, _V_co], /) -> _V_co:
    with pytest.raises(StopIteration) as exc_info:
        gen.send(None)
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


def is_proactor_event_loop(event_loop: asyncio.AbstractEventLoop) -> bool:
    try:
        ProactorEventLoop: type[asyncio.AbstractEventLoop] = getattr(asyncio, "ProactorEventLoop")
    except AttributeError:
        return False
    return isinstance(event_loop, ProactorEventLoop)


def is_uvloop_event_loop(event_loop: asyncio.AbstractEventLoop) -> bool:
    try:
        uvloop = importlib.import_module("uvloop")
    except ModuleNotFoundError:
        return False
    return isinstance(event_loop, uvloop.Loop)


_TooShortBufferBehavior: TypeAlias = Literal["error", "fill_at_most", "xfail"]


def write_in_buffer(
    buffer: WriteableBuffer,
    to_write: bytes,
    *,
    start_pos: int | None = None,
    too_short_buffer: _TooShortBufferBehavior = "error",
) -> int:
    nbytes = len(to_write)
    with memoryview(buffer) as buffer, buffer[start_pos or 0 :] as buffer:
        if len(buffer) >= nbytes:
            buffer[:nbytes] = to_write
        else:
            match too_short_buffer:
                case "error":
                    raise ValueError(f"Buffer is too short to contain the chunk to write. ({len(buffer)} < {nbytes})")
                case "xfail":
                    pytest.xfail(f"Buffer is too short to contain the chunk to write. ({len(buffer)} < {nbytes})")
                case "fill_at_most":
                    nbytes = len(buffer)
                    buffer[:] = memoryview(to_write)[:nbytes]
                case _:
                    assert_never(too_short_buffer)
    return nbytes


def write_data_and_extra_in_buffer(
    buffer: WriteableBuffer,
    complete_data: bytes,
    extra_data: bytes,
    *,
    start_pos: int | None = None,
    too_short_buffer_for_complete_data: _TooShortBufferBehavior = "error",
    too_short_buffer_for_extra_data: _TooShortBufferBehavior = "fill_at_most",
) -> tuple[int, bytes]:
    if start_pos is None:
        start_pos = 0

    complete_data_nbytes = write_in_buffer(
        buffer,
        complete_data,
        start_pos=start_pos,
        too_short_buffer=too_short_buffer_for_complete_data,
    )
    if not extra_data:
        return complete_data_nbytes, extra_data

    extra_data_nbytes = write_in_buffer(
        buffer,
        extra_data,
        start_pos=start_pos + complete_data_nbytes,
        too_short_buffer=too_short_buffer_for_extra_data,
    )
    return complete_data_nbytes + extra_data_nbytes, extra_data[:extra_data_nbytes]


@contextlib.contextmanager
def temporary_exception_handler(
    event_loop: asyncio.AbstractEventLoop,
    handler: asyncio.events._ExceptionHandler | None,
) -> Iterator[None]:
    with contextlib.ExitStack() as stack:
        stack.callback(event_loop.set_exception_handler, event_loop.get_exception_handler())
        event_loop.set_exception_handler(handler)
        yield


@contextlib.contextmanager
def temporary_task_factory(
    event_loop: asyncio.AbstractEventLoop,
    task_factory: asyncio.events._TaskFactory | None,
) -> Iterator[None]:
    with contextlib.ExitStack() as stack:
        stack.callback(event_loop.set_task_factory, event_loop.get_task_factory())
        event_loop.set_task_factory(task_factory)
        yield
