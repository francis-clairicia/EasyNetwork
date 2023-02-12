# -*- coding: Utf-8 -*-

from __future__ import annotations

from types import TracebackType


class DummyLock:
    """
    Helper class used to mock threading.Lock and threading.RLock classes
    """

    def __init__(self) -> None:
        pass

    def __enter__(self) -> bool:
        return self.acquire()

    def __exit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None) -> None:
        self.release()

    def acquire(self, blocking: bool = True, timeout: float = 0) -> bool:
        return True

    def release(self) -> None:
        pass
