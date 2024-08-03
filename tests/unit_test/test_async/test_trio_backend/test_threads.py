from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from trio import Nursery


@pytest.mark.feature_trio(async_test_auto_mark=True)
class TestRunSyncSoonWaiter:

    async def test____aclose____wait_for_thread_to_call_detach(self, nursery: Nursery) -> None:
        # Arrange
        import trio

        from easynetwork.lowlevel.api_async.backend._trio.threads import _PortalRunSyncSoonWaiter

        waiter = _PortalRunSyncSoonWaiter()

        waiter.attach_from_any_thread()

        def in_thread() -> None:
            time.sleep(0.5)
            trio.from_thread.run_sync(waiter.detach_in_trio_thread)

        nursery.start_soon(trio.to_thread.run_sync, in_thread)

        with trio.fail_after(2):
            await waiter.aclose()
