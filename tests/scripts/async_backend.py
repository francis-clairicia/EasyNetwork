# -*- coding: Utf-8 -*-

from __future__ import annotations

import asyncio

from easynetwork.asyncio.backend import AsyncBackendFactory


async def hello_world() -> None:
    print("Hello World!")


async def main() -> None:
    backend = AsyncBackendFactory.new()
    backend.schedule_task(hello_world)
    await backend.yield_task()
    return


if __name__ == "__main__":
    asyncio.run(main())
