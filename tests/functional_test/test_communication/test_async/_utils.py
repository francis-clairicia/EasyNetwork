from __future__ import annotations

from collections.abc import Awaitable, Callable

from easynetwork.lowlevel.api_async.backend.utils import ensure_backend


async def delay[*P, R](delay: float, coroutine_cb: Callable[[*P], Awaitable[R]], /, *args: *P) -> R:
    backend = ensure_backend(None)
    await backend.sleep(delay)
    return await coroutine_cb(*args)
