# Copyright 2021-2024, Francis Clairicia-Rose-Claire-Josephine
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
"""trio engine for easynetwork.api_async
"""

from __future__ import annotations

__all__ = ["convert_trio_resource_errors"]

import contextlib
import errno as _errno
import types

import trio

from .... import _utils


class convert_trio_resource_errors(contextlib.AbstractContextManager[None]):
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
        if not self._locked and not self._lot:
            self._locked = True
        else:
            await self._lot.park()
            assert self._locked  # nosec assert_used

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
