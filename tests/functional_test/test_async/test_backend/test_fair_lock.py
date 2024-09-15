from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypeVarTuple

from easynetwork.lowlevel.api_async.backend.abc import AsyncBackend, IEvent, ILock
from easynetwork.lowlevel.api_async.backend.utils import new_builtin_backend

import pytest
import sniffio

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


_T_Args = TypeVarTuple("_T_Args")


class TestFairLock:
    @pytest.fixture(
        scope="class",
        autouse=True,
        params=[
            pytest.param("asyncio", marks=pytest.mark.asyncio),
            pytest.param("trio", marks=pytest.mark.feature_trio(async_test_auto_mark=True)),
        ],
    )
    @staticmethod
    def backend(request: pytest.FixtureRequest) -> AsyncBackend:
        return new_builtin_backend(request.param)

    @pytest.fixture(params=["default", "custom"])
    @staticmethod
    def fair_lock(request: pytest.FixtureRequest, backend: AsyncBackend) -> ILock:
        from easynetwork.lowlevel.api_async.backend._common.fair_lock import FairLock

        match request.param:
            case "default":
                return FairLock(backend)
            case "custom":
                lock = backend.create_fair_lock()
                if isinstance(lock, FairLock):
                    pytest.skip("uses default implementation with 'custom' parameter")
                return lock
            case _:
                pytest.fail(f"Invalid param: {request.param!r}")

    @staticmethod
    def call_soon(f: Callable[[*_T_Args], Any], *args: *_T_Args) -> None:
        match sniffio.current_async_library():
            case "asyncio":
                import asyncio

                asyncio.get_running_loop().call_soon(f, *args)
            case "trio":
                import trio

                trio.lowlevel.current_trio_token().run_sync_soon(f, *args)
            case _:
                pytest.fail("unknown async library")

    async def test____acquire____fifo_acquire____manual(
        self,
        fair_lock: ILock,
        backend: AsyncBackend,
    ) -> None:
        results: list[int] = []

        async def coroutine(index: int) -> None:
            await fair_lock.acquire()
            try:
                results.append(index)
            finally:
                fair_lock.release()

        assert not fair_lock.locked()
        async with backend.create_task_group() as task_group:

            await fair_lock.acquire()
            try:
                assert fair_lock.locked()
                results.append(0)

                for index in range(1, 4):
                    await task_group.start(coroutine, index)
            finally:
                fair_lock.release()

        assert not fair_lock.locked()
        assert results == [0, 1, 2, 3]

    async def test____acquire____fifo_acquire____context_manager(
        self,
        fair_lock: ILock,
        backend: AsyncBackend,
    ) -> None:
        results: list[int] = []

        async def coroutine(index: int) -> None:
            async with fair_lock:
                results.append(index)

        assert not fair_lock.locked()
        async with backend.create_task_group() as task_group:
            async with fair_lock:
                assert fair_lock.locked()
                results.append(0)

                for index in range(1, 4):
                    await task_group.start(coroutine, index)

        assert not fair_lock.locked()
        assert results == [0, 1, 2, 3]

    async def test____acquire____fast_acquire(
        self,
        fair_lock: ILock,
        backend: AsyncBackend,
        mocker: MockerFixture,
    ) -> None:
        other_task = mocker.async_stub()

        assert not fair_lock.locked()
        async with backend.create_task_group() as task_group:
            task_group.start_soon(other_task)
            async with fair_lock:
                assert fair_lock.locked()

            other_task.assert_called_once()
            other_task.assert_not_awaited()

    async def test____acquire____cancelled(
        self,
        fair_lock: ILock,
        backend: AsyncBackend,
    ) -> None:
        async with backend.create_task_group() as task_group:

            await fair_lock.acquire()

            acquire_task = await task_group.start(fair_lock.acquire)

            assert acquire_task.cancel()

            with pytest.raises(backend.get_cancelled_exc_class()):
                await acquire_task.join()

            assert fair_lock.locked()
            fair_lock.release()
            assert not fair_lock.locked()

    # Taken from asyncio.Lock unit tests
    async def test____acquire____cancel_race(
        self,
        fair_lock: ILock,
        backend: AsyncBackend,
    ) -> None:
        # Several tasks:
        # - A acquires the lock
        # - B is blocked in acquire()
        # - C is blocked in acquire()
        #
        # Now, concurrently:
        # - B is cancelled
        # - A releases the lock
        #
        # If B's waiter is marked cancelled but not yet removed from
        # _waiters, A's release() call will crash when trying to set
        # B's waiter; instead, it should move on to C's waiter.

        async def lockit(name: str, blocker: IEvent | None) -> None:
            await fair_lock.acquire()
            try:
                if blocker is not None:
                    await blocker.wait()
            finally:
                fair_lock.release()

        async with backend.create_task_group() as task_group:

            blocker_a = backend.create_event()
            await task_group.start(lockit, "A", blocker_a)
            assert fair_lock.locked()

            task_b = await task_group.start(lockit, "B", None)
            task_c = await task_group.start(lockit, "C", None)

            # Create the race and check.
            # Without the fix this failed at the last assert.
            blocker_a.set()
            task_b.cancel()
            with backend.timeout(0.200):
                await task_c.join()

    # Taken from asyncio.Lock unit tests
    async def test____acquire____cancel_release_race(
        self,
        fair_lock: ILock,
        backend: AsyncBackend,
    ) -> None:
        # Acquire 4 locks, cancel second, release first
        # and 2 locks are taken at once.

        lock_count: int = 0
        call_count: int = 0

        async def lockit() -> None:
            nonlocal lock_count
            nonlocal call_count
            call_count += 1
            await fair_lock.acquire()
            lock_count += 1

        async with backend.create_task_group() as task_group:

            await fair_lock.acquire()

            # Start scheduled tasks
            t1 = await task_group.start(lockit)
            t2 = await task_group.start(lockit)
            t3 = await task_group.start(lockit)

            def trigger() -> None:
                t1.cancel()
                fair_lock.release()

            self.call_soon(trigger)
            with pytest.raises(backend.get_cancelled_exc_class()):
                # Wait for cancellation
                await t1.join()

            # Make sure only one lock was taken
            for _ in range(3):
                if not lock_count:
                    await backend.coro_yield()
            assert lock_count == 1
            # While 3 calls were made to lockit()
            assert call_count == 3
            assert t1.cancelled() and t2.done()

            # Cleanup the task that is stuck on acquire.
            t3.cancel()
            with backend.move_on_after(0.200):
                await t3.wait()
            assert t3.cancelled()

    async def test____release____not_acquired(
        self,
        fair_lock: ILock,
    ) -> None:
        with pytest.raises(RuntimeError):
            fair_lock.release()

    async def test____release____no_waiters(
        self,
        fair_lock: ILock,
    ) -> None:
        await fair_lock.acquire()
        assert fair_lock.locked()

        fair_lock.release()
        assert not fair_lock.locked()
