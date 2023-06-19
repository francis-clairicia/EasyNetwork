# -*- coding: utf-8 -*-

from __future__ import annotations

import functools
from types import TracebackType
from typing import Any


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


class AsyncDummyLock:
    """
    Helper class used to mock asyncio.Lock classes
    """

    def __init__(self) -> None:
        pass

    async def __aenter__(self) -> None:
        await self.acquire()

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None
    ) -> None:
        self.release()

    async def acquire(self) -> bool:
        return True

    def release(self) -> None:
        pass


class partial_eq(functools.partial[Any]):
    """Helper to check equality with two functools.partial() object

    (c.f. https://github.com/python/cpython/issues/47814)
    """

    def __eq__(self, other: object, /) -> bool:
        if not isinstance(other, functools.partial):
            return NotImplemented
        return self.func == other.func and self.args == other.args and self.keywords == other.keywords


def get_all_socket_families() -> frozenset[str]:
    return _get_all_socket_families()


@functools.cache
def _get_all_socket_families() -> frozenset[str]:
    import socket

    return frozenset(v for v in dir(socket) if v.startswith("AF_"))
