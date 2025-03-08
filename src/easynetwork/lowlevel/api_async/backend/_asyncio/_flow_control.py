# Copyright 2021-2025, Francis Clairicia-Rose-Claire-Josephine
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
#
"""asyncio engine for easynetwork.api_async"""

from __future__ import annotations

__all__ = ["WriteFlowControl"]

import asyncio
import collections
import errno as _errno
import traceback
import types
from collections.abc import Callable

from .... import _utils
from .tasks import TaskUtils


class WriteFlowControl:
    __slots__ = (
        "__loop",
        "__is_closing",
        "__drain_waiters",
        "__write_paused",
        "__connection_lost",
        "__connection_lost_errno",
        "__connection_lost_exception",
        "__connection_lost_exception_tb",
    )

    def __init__(
        self,
        transport: asyncio.BaseTransport,
        loop: asyncio.AbstractEventLoop,
        *,
        connection_lost_errno: int = _errno.ECONNABORTED,
    ) -> None:
        self.__loop: asyncio.AbstractEventLoop = loop
        self.__is_closing: Callable[[], bool] = transport.is_closing
        self.__drain_waiters: collections.deque[asyncio.Future[None]] = collections.deque()
        self.__write_paused: bool = False
        self.__connection_lost: bool = False
        self.__connection_lost_errno: int = connection_lost_errno
        self.__connection_lost_exception: Exception | None = None
        self.__connection_lost_exception_tb: types.TracebackType | None = None

    def writing_paused(self) -> bool:
        return self.__write_paused

    async def drain(self) -> None:
        if self.__is_closing():
            await TaskUtils.coro_yield()
        if self.__connection_lost:
            if self.__connection_lost_exception is not None:
                raise self.__connection_lost_exception.with_traceback(self.__connection_lost_exception_tb)
            raise _utils.error_from_errno(self.__connection_lost_errno)
        if not self.__write_paused:
            return
        waiter = self.__loop.create_future()
        self.__drain_waiters.append(waiter)
        waiter.add_done_callback(self.__drain_waiters.remove)
        try:
            await waiter
        finally:
            del waiter

    def pause_writing(self) -> None:
        self.__write_paused = True

    def resume_writing(self) -> None:
        self.__write_paused = False

        for waiter in self.__drain_waiters:
            if not waiter.done():
                waiter.set_result(None)

    def connection_lost(self, exc: Exception | None) -> None:
        if self.__connection_lost:  # Already called, bail out.
            return
        self.__write_paused = False
        self.__connection_lost = True
        self.__connection_lost_exception = exc
        if exc is not None:
            self.__connection_lost_exception_tb = exc.__traceback__
            self.__loop.call_soon(traceback.clear_frames, exc.__traceback__)

        for waiter in self.__drain_waiters:
            if not waiter.done():
                if exc is None:
                    waiter.set_exception(_utils.error_from_errno(self.__connection_lost_errno))
                else:
                    waiter.set_exception(exc)


# Taken from asyncio library (https://github.com/python/cpython/tree/v3.12.0/Lib/asyncio)
def add_flowcontrol_defaults(high: int | None, low: int | None, kb: int) -> tuple[int, int]:  # pragma: no cover
    if high is None:
        if low is None:
            hi = kb * 1024
        else:
            lo = low
            hi = 4 * lo
    else:
        hi = high
    if low is None:
        lo = hi // 4
    else:
        lo = low

    if not hi >= lo >= 0:
        raise ValueError(f"high ({hi!r}) must be >= low ({lo!r}) must be >= 0")

    return hi, lo
