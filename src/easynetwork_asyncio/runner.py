# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""asyncio engine for easynetwork.api_async
"""

from __future__ import annotations

__all__ = ["AsyncioRunner"]

import asyncio
import contextlib
from collections.abc import Callable, Coroutine
from typing import Any, Self, TypeVar

from easynetwork.api_async.backend.abc import AbstractRunner

_T = TypeVar("_T")


class AsyncioRunner(AbstractRunner):
    __slots__ = ("__runner",)

    def __init__(self, runner: asyncio.Runner) -> None:
        super().__init__()

        self.__runner: asyncio.Runner = runner

    def __enter__(self) -> Self:
        self.__runner.__enter__()
        return super().__enter__()

    def close(self) -> None:
        return self.__runner.close()

    def run(self, coro_func: Callable[..., Coroutine[Any, Any, _T]], *args: Any) -> _T:
        with contextlib.closing(coro_func(*args)) as coro:  # Avoid ResourceWarning by always closing the coroutine
            return self.__runner.run(coro)
