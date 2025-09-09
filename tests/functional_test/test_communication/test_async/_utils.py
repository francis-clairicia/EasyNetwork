from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar, TypeVarTuple

_T = TypeVar("_T")
_T_Args = TypeVarTuple("_T_Args")


async def delay(delay: float, coroutine_cb: Callable[[*_T_Args], Awaitable[_T]], /, *args: *_T_Args) -> _T:
    await asyncio.sleep(delay)
    return await coroutine_cb(*args)
