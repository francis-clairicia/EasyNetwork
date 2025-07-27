from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio


@pytest_asyncio.fixture(params=[True, False], ids=lambda p: f"enable_eager_tasks=={p}")
async def enable_eager_tasks(request: pytest.FixtureRequest) -> bool:
    enable_eager_tasks = bool(request.param)
    if enable_eager_tasks:
        event_loop = asyncio.get_running_loop()
        try:
            eager_task_factory = getattr(asyncio, "eager_task_factory")
        except AttributeError:
            pytest.skip("asyncio.eager_task_factory not implemented")
        else:
            event_loop.set_task_factory(eager_task_factory)
    return enable_eager_tasks
