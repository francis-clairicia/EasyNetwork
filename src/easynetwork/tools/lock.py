# -*- coding: utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""
Synchronization primitive extension module
"""

from __future__ import annotations

__all__ = ["ForkSafeLock"]

import os
import threading
from typing import Callable, Generic, TypeVar, cast, overload

_L = TypeVar("_L", bound="threading.RLock | threading.Lock")


class ForkSafeLock(Generic[_L]):
    __slots__ = ("__pid", "__unsafe_lock", "__lock_factory", "__weakref__")

    @overload
    def __init__(self: ForkSafeLock[threading.RLock], lock_factory: None = ...) -> None:
        ...

    @overload
    def __init__(self, lock_factory: Callable[[], _L]) -> None:
        ...

    def __init__(self, lock_factory: Callable[[], _L] | None = None) -> None:
        if lock_factory is None:
            lock_factory = cast(Callable[[], _L], threading.RLock)
        self.__unsafe_lock: _L = lock_factory()
        self.__pid: int = os.getpid()
        self.__lock_factory: Callable[[], _L] = lock_factory

    def get(self) -> _L:
        if self.__pid != os.getpid():
            self.__unsafe_lock = self.__lock_factory()
            self.__pid = os.getpid()
        return self.__unsafe_lock
