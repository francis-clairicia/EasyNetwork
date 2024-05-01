from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import pytest_asyncio


@dataclass(repr=False, eq=False, kw_only=True, frozen=True, slots=True, weakref_slot=True)
class AsyncFinalizer:
    add_finalizer: Callable[[Callable[[], Awaitable[Any]]], None]


@pytest_asyncio.fixture
async def async_finalizer(request: Any) -> AsyncIterator[AsyncFinalizer]:
    async with contextlib.AsyncExitStack() as stack:

        def add_finalizer(f: Callable[[], Awaitable[Any]]) -> None:
            stack.push_async_callback(f)

        yield AsyncFinalizer(add_finalizer=add_finalizer)
