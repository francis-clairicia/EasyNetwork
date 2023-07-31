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
            loop = self.__runner.get_loop()
            try:
                return self.__runner.run(coro)
            finally:
                _cancel_all_tasks(loop)
                loop.run_until_complete(loop.shutdown_asyncgens())


def _cancel_all_tasks(loop: asyncio.AbstractEventLoop) -> None:  # pragma: no cover
    # Exact copy of what runner.close() would do
    # Ref: https://github.com/python/cpython/blob/3.11/Lib/asyncio/runners.py#L193

    to_cancel = asyncio.all_tasks(loop)
    if not to_cancel:
        return

    for task in to_cancel:
        task.cancel()

    loop.run_until_complete(asyncio.gather(*to_cancel, return_exceptions=True))

    for task in to_cancel:
        if task.cancelled():
            continue
        if task.exception() is not None:
            loop.call_exception_handler(
                {
                    "message": "unhandled exception during asyncio.run() shutdown",
                    "exception": task.exception(),
                    "task": task,
                }
            )
