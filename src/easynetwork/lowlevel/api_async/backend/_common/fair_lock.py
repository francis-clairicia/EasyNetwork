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
"""Fair lock module."""

from __future__ import annotations

__all__ = ["FairLock"]

from collections import deque
from types import TracebackType

from .... import _utils
from ..abc import AsyncBackend, IEvent, ILock


class FairLock:
    """
    A Lock object for inter-task synchronization where tasks are guaranteed to acquire the lock in strict
    first-come-first-served order. This means that it always goes to the task which has been waiting longest.
    """

    def __init__(self, backend: AsyncBackend) -> None:
        self._backend: AsyncBackend = backend
        self._waiters: deque[IEvent] | None = None
        self._locked: bool = False

    def __repr__(self) -> str:
        res = super().__repr__()
        extra = "locked" if self._locked else "unlocked"
        if self._waiters:
            extra = f"{extra}, waiters:{len(self._waiters)}"
        return f"<{res[1:-1]} [{extra}]>"

    @_utils.inherit_doc(ILock)
    async def __aenter__(self) -> None:
        await self.acquire()

    @_utils.inherit_doc(ILock)
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
        /,
    ) -> None:
        self.release()

    @_utils.inherit_doc(ILock)
    async def acquire(self) -> None:
        if self._locked or self._waiters:
            if self._waiters is None:
                self._waiters = deque()

            waiter = self._backend.create_event()
            self._waiters.append(waiter)
            try:
                try:
                    await waiter.wait()
                finally:
                    self._waiters.remove(waiter)
            except BaseException:
                if not self._locked:
                    self._wake_up_first()
                raise

        self._locked = True

    @_utils.inherit_doc(ILock)
    def release(self) -> None:
        if self._locked:
            self._locked = False
            self._wake_up_first()
        else:
            raise RuntimeError("Lock not acquired")

    def _wake_up_first(self) -> None:
        if not self._waiters:
            return

        waiter = self._waiters[0]
        waiter.set()

    @_utils.inherit_doc(ILock)
    def locked(self) -> bool:
        return self._locked
