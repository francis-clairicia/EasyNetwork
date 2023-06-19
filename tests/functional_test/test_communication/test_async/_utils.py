# -*- coding: utf-8 -*-

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, TypeVar

_T = TypeVar("_T")


async def delay(coroutine_cb: Callable[[], Awaitable[_T]], delay: float) -> _T:
    await asyncio.sleep(delay)
    return await coroutine_cb()
