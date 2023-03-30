# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Asynchronous tools module"""

from __future__ import annotations

__all__ = ["run_task_once"]

from typing import TYPE_CHECKING, Awaitable, Callable, TypeVar

if TYPE_CHECKING:
    import concurrent.futures

    from .abc import AbstractAsyncBackend

_T = TypeVar("_T")


async def run_task_once(
    coroutine_cb: Callable[[], Awaitable[_T]],
    task_future: concurrent.futures.Future[_T],
    backend: AbstractAsyncBackend,
) -> _T:
    if task_future.done():
        return task_future.result()
    if task_future.running():
        del coroutine_cb
        return await backend.wait_future(task_future)
    try:
        task_future.set_running_or_notify_cancel()
        result: _T = await coroutine_cb()
    except BaseException as exc:
        task_future.set_exception(exc)
        raise
    else:
        task_future.set_result(result)
        return result
    finally:
        del task_future, coroutine_cb
