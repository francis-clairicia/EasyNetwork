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
"""
Synchronization primitive extension module
"""

from __future__ import annotations

__all__ = ["ForkSafeLock"]

import dataclasses
import os
import threading
from collections.abc import Callable
from typing import Any, Generic, TypeVar, cast, overload

_T_Lock = TypeVar("_T_Lock", bound="threading.RLock | threading.Lock")


class ForkSafeLock(Generic[_T_Lock]):
    __slots__ = ("__pid", "__unsafe_lock", "__lock_factory", "__weakref__")

    @overload
    def __init__(self: ForkSafeLock[threading.RLock], lock_factory: None = ...) -> None: ...

    @overload
    def __init__(self, lock_factory: Callable[[], _T_Lock]) -> None: ...

    def __init__(self, lock_factory: Callable[[], _T_Lock] | None = None) -> None:
        if lock_factory is None:
            lock_factory = cast(Callable[[], _T_Lock], threading.RLock)
        self.__unsafe_lock: _T_Lock = lock_factory()
        self.__pid: int = os.getpid()
        self.__lock_factory: Callable[[], _T_Lock] = lock_factory

    def get(self) -> _T_Lock:
        if self.__pid != os.getpid():
            self.__unsafe_lock = self.__lock_factory()
            self.__pid = os.getpid()
        return self.__unsafe_lock


class RWLock:
    __slots__ = ("__read_lock", "__readers_nb", "__write_lock")

    @dataclasses.dataclass(frozen=True, kw_only=True, eq=False, slots=True)
    class Lock:
        acquire: Callable[[], None]
        release: Callable[[], None]

        def __enter__(self) -> None:
            self.acquire()

        def __exit__(self, *exc_args: Any) -> None:
            self.release()

    def __init__(self) -> None:
        self.__read_lock = threading.Lock()
        self.__readers_nb = 0
        self.__write_lock = threading.Lock()

    def acquire_read(self) -> None:
        with self.__read_lock:
            self.__readers_nb += 1
            if self.__readers_nb == 1:
                self.__write_lock.acquire()

    def release_read(self) -> None:
        with self.__read_lock:
            if self.__readers_nb < 1:
                raise RuntimeError("release unlocked lock")
            self.__readers_nb -= 1
            if self.__readers_nb == 0:
                self.__write_lock.release()

    def read_lock(self) -> RWLock.Lock:
        return self.Lock(acquire=self.acquire_read, release=self.release_read)

    def acquire_write(self) -> None:
        self.__write_lock.acquire()

    def release_write(self) -> None:
        self.__write_lock.release()

    def write_lock(self) -> RWLock.Lock:
        return self.Lock(acquire=self.acquire_write, release=self.release_write)
