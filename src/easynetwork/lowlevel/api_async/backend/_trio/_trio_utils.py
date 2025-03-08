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
"""trio engine for easynetwork.api_async"""

from __future__ import annotations

__all__ = [
    "FastFIFOLock",
    "close_socket_and_notify",
    "convert_trio_resource_errors",
    "retry_socket_method",
]

import contextlib
import errno as _errno
import socket as _socket
import types
from collections.abc import Awaitable, Callable
from typing import TypeVar

import trio
from trio.lowlevel import (
    cancel_shielded_checkpoint as _trio_cancel_shielded_checkpoint,
    checkpoint_if_cancelled as _trio_checkpoint_if_cancelled,
)

from .... import _utils

_T_Socket = TypeVar("_T_Socket", bound=_socket.socket)
_T_Return = TypeVar("_T_Return")


class convert_trio_resource_errors(contextlib.AbstractContextManager[None, None]):
    def __init__(self, *, broken_resource_errno: int) -> None:
        self.__broken_resource_errno: int = broken_resource_errno

    def __enter__(self) -> None:
        return

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: types.TracebackType | None,
    ) -> None:
        if exc_type is None:
            return

        if exc_value is None:
            exc_value = exc_type()  # pragma: no cover

        try:
            if issubclass(exc_type, trio.ClosedResourceError):
                raise self.__get_error_from_cause(exc_value, _errno.EBADF)
            if issubclass(exc_type, trio.BrokenResourceError):
                raise self.__get_error_from_cause(exc_value, self.__broken_resource_errno)
            if issubclass(exc_type, trio.BusyResourceError):
                raise self.__get_error_from_cause(exc_value, _errno.EBUSY)
        except BaseException as new_exc:
            _utils.remove_traceback_frames_in_place(new_exc, 1)
            raise
        finally:
            del exc_value, traceback

    @staticmethod
    def __get_error_from_cause(
        exc_value: BaseException,
        fallback_errno: int,
    ) -> OSError:
        match exc_value.__cause__:
            case OSError() as error:
                error.__cause__ = None
                error.__suppress_context__ = True
                return error
            case _:
                error = _utils.error_from_errno(fallback_errno)
                error.__cause__ = exc_value
                error.__suppress_context__ = True
                return error.with_traceback(None)


class FastFIFOLock:

    def __init__(self) -> None:
        self._locked: bool = False
        self._lot: trio.lowlevel.ParkingLot = trio.lowlevel.ParkingLot()

    def __repr__(self) -> str:
        res = super().__repr__()
        extra = "locked" if self._locked else "unlocked"
        if self._lot:
            extra = f"{extra}, waiters:{len(self._lot)}"
        return f"<{res[1:-1]} [{extra}]>"

    async def __aenter__(self) -> None:
        await self.acquire()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
        /,
    ) -> None:
        self.release()

    async def acquire(self) -> None:
        await _trio_checkpoint_if_cancelled()
        if self._locked or self._lot:
            await self._lot.park()
            if not self._locked:
                raise AssertionError("should be acquired")
        else:
            self._locked = True

    def release(self) -> None:
        if self._locked:
            if self._lot:
                self._lot.unpark(count=1)
            else:
                self._locked = False
        else:
            raise RuntimeError("Lock not acquired")

    def locked(self) -> bool:
        return self._locked


async def connect_sock_to_resolved_address(sock: _socket.socket, address: _socket._Address) -> None:
    await trio.lowlevel.checkpoint_if_cancelled()
    try:
        sock.connect(address)
    except BlockingIOError:
        pass
    else:
        await trio.lowlevel.cancel_shielded_checkpoint()
        return

    await trio.lowlevel.wait_writable(sock)
    _utils.check_real_socket_state(sock, error_msg=f"Could not connect to {address!r}: {{strerror}}")


def close_socket_and_notify(sock: _socket.socket) -> None:
    if sock.fileno() >= 0:
        trio.lowlevel.notify_closing(sock)
        sock.close()


async def retry_socket_method(
    waiter: Callable[[_T_Socket], Awaitable[None]],
    sock: _T_Socket,
    callback: Callable[[], _T_Return],
    /,
    *,
    always_yield: bool,
    checkpoint_if_cancelled: bool = True,
    exceptions_to_catch: type[Exception] | tuple[type[Exception], ...] = BlockingIOError,
) -> _T_Return:
    if checkpoint_if_cancelled:
        await _trio_checkpoint_if_cancelled()
    while True:
        try:
            result = callback()
        except exceptions_to_catch:
            pass
        else:
            if always_yield:
                await _trio_cancel_shielded_checkpoint()
            return result

        await waiter(sock)
        always_yield = False  # <- Already done the line just above
