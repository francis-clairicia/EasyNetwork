from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

_T = TypeVar("_T")


async def delay(coroutine_cb: Callable[[], Awaitable[_T]], delay: float) -> _T:
    await asyncio.sleep(delay)
    return await coroutine_cb()
