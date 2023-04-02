# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""asyncio engine for easynetwork.api_async
"""

from __future__ import annotations

__all__ = ["Task", "TaskGroup"]

import asyncio
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Self, final

from easynetwork.api_async.backend.abc import AbstractTaskGroup, ITask

if TYPE_CHECKING:
    from types import TracebackType


class Task:
    __slots__ = ("__t", "__weakref__")

    def __init__(self, task: asyncio.Task[Any]) -> None:
        self.__t: asyncio.Task[Any] = task

    def get_name(self) -> str:
        return self.__t.get_name()

    def get_coro(self) -> Coroutine[Any, Any, Any]:
        return self.__t.get_coro()  # type: ignore[return-value]

    def done(self) -> bool:
        return self.__t.done()

    def cancel(self) -> None:
        self.__t.cancel()


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

    async def start(self, func: Callable[..., Coroutine[Any, Any, Any]], *args: Any, name: str | None = None) -> ITask:
        task = self.__asyncio_tg.create_task(func(*args), name=name)
        await asyncio.sleep(0)
        return Task(task)

    def start_soon(self, func: Callable[..., Coroutine[Any, Any, Any]], *args: Any, name: str | None = None) -> None:
        self.__asyncio_tg.create_task(func(*args), name=name)
