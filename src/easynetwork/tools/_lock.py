# Copyright 2021-2023, Francis Clairicia-Rose-Claire-Josephine
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

import os
import threading
from collections.abc import Callable
from typing import Generic, TypeVar, cast, overload

_LockType = TypeVar("_LockType", bound="threading.RLock | threading.Lock")


class ForkSafeLock(Generic[_LockType]):
    __slots__ = ("__pid", "__unsafe_lock", "__lock_factory", "__weakref__")

    @overload
    def __init__(self: ForkSafeLock[threading.RLock], lock_factory: None = ...) -> None:
        ...

    @overload
    def __init__(self, lock_factory: Callable[[], _LockType]) -> None:
        ...

    def __init__(self, lock_factory: Callable[[], _LockType] | None = None) -> None:
        if lock_factory is None:
            lock_factory = cast(Callable[[], _LockType], threading.RLock)
        self.__unsafe_lock: _LockType = lock_factory()
        self.__pid: int = os.getpid()
        self.__lock_factory: Callable[[], _LockType] = lock_factory

    def get(self) -> _LockType:
        if self.__pid != os.getpid():
            self.__unsafe_lock = self.__lock_factory()
            self.__pid = os.getpid()
        return self.__unsafe_lock
