from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar, TypeVarTuple

from easynetwork.lowlevel.api_async.backend.utils import ensure_backend

_T = TypeVar("_T")
_T_Args = TypeVarTuple("_T_Args")


async def delay(delay: float, coroutine_cb: Callable[[*_T_Args], Awaitable[_T]], /, *args: *_T_Args) -> _T:
    backend = ensure_backend(None)
    await backend.sleep(delay)
    return await coroutine_cb(*args)
