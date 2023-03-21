# -*- coding: Utf-8 -*-

from __future__ import annotations

import asyncio

from easynetwork.async_def.backend import AsyncBackendFactory


async def hello_world() -> None:
    print("Hello World!")


async def main() -> None:
    backend = AsyncBackendFactory.new()
    asyncio.create_task(hello_world())
    await backend.sleep(0)
    return


if __name__ == "__main__":
    asyncio.run(main())
