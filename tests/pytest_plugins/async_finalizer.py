from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import pytest_asyncio

from ..fixtures.trio import trio_fixture


@dataclass(repr=False, eq=False, kw_only=True, frozen=True, slots=True, weakref_slot=True)
class AsyncFinalizer:
    add_finalizer: Callable[[Callable[[], Awaitable[Any]]], None]


@pytest_asyncio.fixture
async def async_finalizer(request: Any) -> AsyncIterator[AsyncFinalizer]:
    import asyncio

    asyncio.get_running_loop()

    async with contextlib.AsyncExitStack() as stack:

        def add_finalizer(f: Callable[[], Awaitable[Any]]) -> None:
            stack.push_async_callback(f)

        yield AsyncFinalizer(add_finalizer=add_finalizer)


@trio_fixture
async def async_finalizer_trio(request: Any) -> AsyncIterator[AsyncFinalizer]:
    import trio

    trio.lowlevel.current_trio_token()

    async with contextlib.AsyncExitStack() as stack:

        def add_finalizer(f: Callable[[], Awaitable[Any]]) -> None:
            stack.push_async_callback(f)

        yield AsyncFinalizer(add_finalizer=add_finalizer)
