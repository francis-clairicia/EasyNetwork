# -*- coding: utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""
Asynchronous client/server module
"""

from __future__ import annotations

__all__ = ["SingleTaskRunner"]

from typing import TYPE_CHECKING, Any, Callable, Coroutine, Generic, ParamSpec, TypeVar

if TYPE_CHECKING:
    from .abc import AbstractAsyncBackend, AbstractTask


_P = ParamSpec("_P")
_T_co = TypeVar("_T_co", covariant=True)


class SingleTaskRunner(Generic[_T_co]):
    __slots__ = (
        "__backend",
        "__coro_func",
        "__task",
        "__weakref__",
    )

    def __init__(
        self,
        __backend: AbstractAsyncBackend,
        __coro_func: Callable[_P, Coroutine[Any, Any, _T_co]],
        /,
        *args: _P.args,
        **kwargs: _P.kwargs,
    ) -> None:
        super().__init__()

        self.__backend: AbstractAsyncBackend = __backend
        self.__coro_func: tuple[Callable[..., Coroutine[Any, Any, _T_co]], tuple[Any, ...], dict[str, Any]] | None = (
            __coro_func,
            args,
            kwargs,
        )
        self.__task: AbstractTask[_T_co] | None = None

    def cancel(self) -> bool:
        self.__coro_func = None
        if self.__task is not None:
            return self.__task.cancel()
        return True

    async def run(self) -> _T_co:
        if self.__task is not None:
            return await self.__task.join()

        try:
            async with self.__backend.create_task_group() as task_group:
                if self.__coro_func is None:
                    self.__task = task_group.start_soon(self.__backend.sleep_forever)
                    self.__task.cancel()
                else:
                    coro_func, args, kwargs = self.__coro_func
                    self.__coro_func = None
                    self.__task = task_group.start_soon(coro_func, *args, **kwargs)
                    del coro_func, args, kwargs
        except BaseExceptionGroup as excgrp:
            if len(excgrp.exceptions) != 1:  # pragma: no cover  # Hard to test
                raise
            # This is most likely the unhandled exception raised by coro_func
            raise excgrp.exceptions[0] from None

        return await self.__task.join()
