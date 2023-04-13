# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""asyncio engine for easynetwork.api_async
"""

from __future__ import annotations

__all__ = ["AsyncioThreadsPortal"]

import asyncio
import threading
from typing import Any, Callable, Coroutine, ParamSpec, TypeVar, final

from easynetwork.api_async.backend.abc import AbstractThreadsPortal

_P = ParamSpec("_P")
_T = TypeVar("_T")


@final
class AsyncioThreadsPortal(AbstractThreadsPortal):
    __slots__ = ("__loop",)

    def __init__(self) -> None:
        super().__init__()
        self.__loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()

    def run_coroutine(self, __coro_func: Callable[_P, Coroutine[Any, Any, _T]], /, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        if threading.get_ident() == self.parent_thread_id:
            raise RuntimeError("must be called in a different OS thread")
        future = asyncio.run_coroutine_threadsafe(__coro_func(*args, **kwargs), self.__loop)
        try:
            return future.result()
        finally:
            del future

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        return self.__loop
