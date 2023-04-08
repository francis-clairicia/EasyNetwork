# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""asyncio engine for easynetwork.api_async
"""

from __future__ import annotations

__all__ = ["Task", "TaskGroup"]

import asyncio
from typing import TYPE_CHECKING, Any, Callable, Coroutine, ParamSpec, Self, TypeVar, final

from easynetwork.api_async.backend.abc import AbstractTask, AbstractTaskGroup

if TYPE_CHECKING:
    from types import TracebackType


_P = ParamSpec("_P")
_T_co = TypeVar("_T_co", covariant=True)


@final
class Task(AbstractTask[_T_co]):
    __slots__ = ("__t",)

    def __init__(self, task: asyncio.Task[_T_co]) -> None:
        self.__t: asyncio.Task[_T_co] = task

    def __hash__(self) -> int:
        return hash(self.__t)

    def __eq__(self, other: object, /) -> bool:
        if not isinstance(other, Task):
            return NotImplemented
        return self.__t == other.__t

    def __ne__(self, other: object, /) -> bool:
        return not (self == other)

    def done(self) -> bool:
        return self.__t.done()

    def cancel(self) -> None:
        self.__t.cancel()

    def cancelled(self) -> bool:
        return self.__t.cancelled()

    async def join(self) -> _T_co:
        return await self.__t


@final
class TaskGroup(AbstractTaskGroup):
    __slots__ = ("__asyncio_tg",)

    def __init__(self) -> None:
        super().__init__()
        self.__asyncio_tg: asyncio.TaskGroup = asyncio.TaskGroup()

    async def __aenter__(self) -> Self:
        asyncio_tg: asyncio.TaskGroup = self.__asyncio_tg
        await type(asyncio_tg).__aenter__(asyncio_tg)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        asyncio_tg: asyncio.TaskGroup = self.__asyncio_tg
        return await type(asyncio_tg).__aexit__(asyncio_tg, exc_type, exc_val, exc_tb)

    def start_soon(
        self,
        __coro_func: Callable[_P, Coroutine[Any, Any, _T_co]],
        /,
        *args: _P.args,
        **kwargs: _P.kwargs,
    ) -> AbstractTask[_T_co]:
        return Task(self.__asyncio_tg.create_task(__coro_func(*args, **kwargs)))
