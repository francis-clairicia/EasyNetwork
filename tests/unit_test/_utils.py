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
