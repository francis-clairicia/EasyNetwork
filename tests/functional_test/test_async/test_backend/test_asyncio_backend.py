# -*- coding: utf-8 -*-

from __future__ import annotations

import asyncio
from concurrent.futures import CancelledError as FutureCancelledError, Future

from easynetwork.api_async.backend.factory import AsyncBackendFactory
from easynetwork_asyncio.backend import AsyncioBackend

import pytest


@pytest.mark.asyncio
class TestAsyncioBackend:
    @pytest.fixture
    @staticmethod
    def backend() -> AsyncioBackend:
        backend = AsyncBackendFactory.new("asyncio")
        assert isinstance(backend, AsyncioBackend)
        return backend

    async def test____use_asyncio_transport____True_by_default(self, backend: AsyncioBackend) -> None:
        assert backend.use_asyncio_transport()

    async def test____cancel_shielded_coro_yield____mute_cancellation(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncioBackend,
    ) -> None:
        task: asyncio.Task[None] = event_loop.create_task(backend.cancel_shielded_coro_yield())

        await asyncio.sleep(0)

        for _ in range(3):
            task.cancel()

        await task
        assert not task.cancelled()

    async def test____ignore_cancellation____always_continue_on_cancellation(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncioBackend,
    ) -> None:
        task: asyncio.Task[int] = event_loop.create_task(backend.ignore_cancellation(asyncio.sleep(0.5, 42)))

        for i in range(5):
            for _ in range(3):
                event_loop.call_later(0.1 * i, task.cancel)

        assert await task == 42
        assert not task.cancelled()

    async def test____ignore_cancellation____task_do_not_appear_in_registered_tasks(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncioBackend,
    ) -> None:
        async def coroutine() -> bool:
            task = asyncio.current_task()
            assert task not in asyncio.all_tasks()
            return True

        task: asyncio.Task[bool] = event_loop.create_task(backend.ignore_cancellation(coroutine()))

        assert await task is True

    async def test____ignore_cancellation____coroutine_cancelled_itself(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncioBackend,
    ) -> None:
        async def self_cancellation() -> None:
            task = asyncio.current_task()
            assert task is not None
            task.cancel()
            await asyncio.sleep(0)
            raise AssertionError

        task = event_loop.create_task(backend.ignore_cancellation(self_cancellation()))

        with pytest.raises(asyncio.CancelledError):
            await task
        assert task.cancelled()

    async def test____timeout____respected(
        self,
        backend: AsyncioBackend,
    ) -> None:
        async with backend.timeout(1):
            assert await asyncio.sleep(0.5, 42) == 42

    async def test____timeout____timeout_error(
        self,
        backend: AsyncioBackend,
    ) -> None:
        with pytest.raises(TimeoutError):
            async with backend.timeout(0.25):
                await asyncio.sleep(0.5, 42)

    async def test____timeout____cancellation(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncioBackend,
    ) -> None:
        async def coroutine() -> None:
            async with backend.timeout(0.25):
                await asyncio.sleep(0.5, 42)

        task = event_loop.create_task(coroutine())
        event_loop.call_later(0.10, task.cancel)

        await asyncio.wait({task})
        assert task.cancelled()

    async def test____timeout_at____respected(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncioBackend,
    ) -> None:
        async with backend.timeout_at(event_loop.time() + 1):
            assert await asyncio.sleep(0.5, 42) == 42

    async def test____timeout_at____timeout_error(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncioBackend,
    ) -> None:
        with pytest.raises(TimeoutError):
            async with backend.timeout_at(event_loop.time() + 0.25):
                await asyncio.sleep(0.5, 42)

    async def test____timeout_at____cancellation(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncioBackend,
    ) -> None:
        async def coroutine() -> None:
            async with backend.timeout_at(event_loop.time() + 0.25):
                await asyncio.sleep(0.5, 42)

        task = event_loop.create_task(coroutine())
        event_loop.call_later(0.10, task.cancel)

        await asyncio.wait({task})
        assert task.cancelled()

    async def test____sleep_forever____sleep_until_cancellation(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncioBackend,
    ) -> None:
        sleep_task = event_loop.create_task(backend.sleep_forever())

        event_loop.call_later(0.5, sleep_task.cancel)

        with pytest.raises(asyncio.CancelledError):
            await sleep_task

    async def test____create_task_group____task_pool(
        self,
        backend: AsyncioBackend,
    ) -> None:
        async def coroutine(value: int) -> int:
            return await asyncio.sleep(0.5, value)

        async with backend.create_task_group() as tg:
            task_42 = tg.start_soon(coroutine, 42)
            task_54 = tg.start_soon(coroutine, 54)

            assert not task_42.done()
            assert not task_54.done()

        assert task_42.done()
        assert task_54.done()
        assert not task_42.cancelled()
        assert not task_54.cancelled()
        assert await task_42.join() == 42
        assert await task_54.join() == 54

        # Join several should not raise
        assert await task_42.join() == 42
        assert await task_54.join() == 54

        # Task already done cannot be cancelled
        assert not task_42.cancel()
        assert not task_54.cancel()
        assert await task_42.join() == 42
        assert await task_54.join() == 54

    async def test____create_task_group____task_cancellation(
        self,
        backend: AsyncioBackend,
    ) -> None:
        async def coroutine(value: int) -> int:
            return await asyncio.sleep(0.5, value)

        async with backend.create_task_group() as tg:
            task_42 = tg.start_soon(coroutine, 42)
            task_54 = tg.start_soon(coroutine, 54)

            await asyncio.sleep(0)
            assert not task_42.done()
            assert not task_54.done()

            assert task_42.cancel()

        assert task_42.done()
        assert task_54.done()
        assert task_42.cancelled()
        assert not task_54.cancelled()
        with pytest.raises(asyncio.CancelledError):
            await task_42.join()
        assert await task_54.join() == 54

        # Tasks cannot be cancelled twice
        assert not task_42.cancel()

    async def test____create_task_group____task_join_cancel_shielding(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncioBackend,
    ) -> None:
        async def coroutine(value: int) -> int:
            return await asyncio.sleep(0.5, value)

        async with backend.create_task_group() as task_group:
            inner_task = task_group.start_soon(coroutine, 42)

            outer_task = event_loop.create_task(inner_task.join())
            event_loop.call_later(0.2, outer_task.cancel)

            with pytest.raises(asyncio.CancelledError):
                await outer_task

            assert outer_task.cancelled()
            assert not inner_task.cancelled()
            assert await inner_task.join() == 42

    async def test____wait_future____wait_until_done(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncioBackend,
    ) -> None:
        future: Future[int] = Future()
        event_loop.call_later(0.5, future.set_result, 42)

        assert await backend.wait_future(future) == 42

    @pytest.mark.parametrize("future_running", [None, "before", "after"], ids=lambda state: f"future_running=={state}")
    async def test____wait_future____cancel_future_if_task_is_cancelled(
        self,
        future_running: str | None,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncioBackend,
    ) -> None:
        future: Future[int] = Future()
        if future_running == "before":
            future.set_running_or_notify_cancel()
            assert future.running()
            event_loop.call_later(0.5, future.set_result, 42)

        task = event_loop.create_task(backend.wait_future(future))
        await asyncio.sleep(0.1)

        if future_running == "after":
            future.set_running_or_notify_cancel()
            assert future.running()
            event_loop.call_later(0.5, future.set_result, 42)

        for _ in range(3):
            task.cancel()
        await asyncio.wait([task])

        if future_running is not None:
            assert not future.cancelled()
            assert not task.cancelled()
            assert task.result() == 42
        else:
            assert future.cancelled()
            assert task.cancelled()

    async def test____wait_future____future_is_cancelled(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncioBackend,
    ) -> None:
        future: Future[int] = Future()
        task = event_loop.create_task(backend.wait_future(future))
        await asyncio.sleep(0)

        future.cancel()
        await asyncio.wait([task])

        assert not task.cancelled()
        assert type(task.exception()) is FutureCancelledError

    async def test____wait_future____already_done(
        self,
        backend: AsyncioBackend,
    ) -> None:
        future: Future[int] = Future()
        future.set_result(42)

        assert await backend.wait_future(future) == 42

    async def test____wait_future____already_cancelled(
        self,
        backend: AsyncioBackend,
    ) -> None:
        future: Future[int] = Future()
        future.cancel()

        with pytest.raises(FutureCancelledError):
            await backend.wait_future(future)

    async def test____run_in_thread____cannot_be_cancelled(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncioBackend,
    ) -> None:
        import time

        task = event_loop.create_task(backend.run_in_thread(time.sleep, 0.5))
        event_loop.call_later(0.1, task.cancel)
        event_loop.call_later(0.2, task.cancel)
        event_loop.call_later(0.3, task.cancel)
        event_loop.call_later(0.4, task.cancel)

        await task

        assert not task.cancelled()

    @pytest.mark.feature_sniffio
    async def test____run_in_thread____sniffio_contextvar_reset(self, backend: AsyncioBackend) -> None:
        import sniffio

        sniffio.current_async_library_cvar.set("asyncio")

        def callback() -> str | None:
            return sniffio.current_async_library_cvar.get()

        cvar_inner = await backend.run_in_thread(callback)
        cvar_outer = sniffio.current_async_library_cvar.get()

        assert cvar_inner is None
        assert cvar_outer == "asyncio"

    async def test____create_threads_portal____run_coroutine_from_thread(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncioBackend,
    ) -> None:
        threads_portal = backend.create_threads_portal()

        async def coroutine(value: int) -> int:
            assert asyncio.get_running_loop() is event_loop
            return await asyncio.sleep(0.5, value)

        with pytest.raises(RuntimeError):
            threads_portal.run_coroutine(coroutine, 42)

        def thread() -> int:
            with pytest.raises(RuntimeError):
                asyncio.get_running_loop()
            return threads_portal.run_coroutine(coroutine, 42)

        assert await backend.run_in_thread(thread) == 42

    async def test____create_threads_portal____run_coroutine_from_thread____can_be_called_from_other_event_loop(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncioBackend,
    ) -> None:
        threads_portal = backend.create_threads_portal()

        async def coroutine(value: int) -> int:
            assert asyncio.get_running_loop() is event_loop
            return await asyncio.sleep(0.5, value)

        def thread() -> int:
            async def main() -> int:
                assert asyncio.get_running_loop() is not event_loop
                return threads_portal.run_coroutine(coroutine, 42)

            return asyncio.run(main())

        assert await backend.run_in_thread(thread) == 42

    async def test____create_threads_portal____run_coroutine_from_thread____exception_raised(
        self,
        backend: AsyncioBackend,
    ) -> None:
        threads_portal = backend.create_threads_portal()
        expected_exception = OSError("Why not?")

        async def coroutine(value: int) -> int:
            raise expected_exception

        def thread() -> int:
            return threads_portal.run_coroutine(coroutine, 42)

        with pytest.raises(OSError) as exc_info:
            await backend.run_in_thread(thread)

        assert exc_info.value is expected_exception

    async def test____create_threads_portal____run_coroutine_from_thread____coroutine_cancelled(
        self,
        backend: AsyncioBackend,
    ) -> None:
        threads_portal = backend.create_threads_portal()

        async def coroutine(value: int) -> int:
            task = asyncio.current_task()
            assert task is not None
            task.get_loop().call_later(0.5, task.cancel)
            await task.get_loop().create_future()
            raise AssertionError("Not cancelled")

        def thread() -> int:
            return threads_portal.run_coroutine(coroutine, 42)

        with pytest.raises(asyncio.CancelledError):
            await backend.run_in_thread(thread)

    async def test____create_threads_portal____run_coroutine_from_thread____explicit_concurrent_future_Cancelled(
        self,
        backend: AsyncioBackend,
    ) -> None:
        threads_portal = backend.create_threads_portal()

        async def coroutine(value: int) -> int:
            raise FutureCancelledError()

        def thread() -> int:
            with pytest.raises(asyncio.CancelledError):  # asyncio do the job to convert the concurrent.futures.CancelledError
                return threads_portal.run_coroutine(coroutine, 42)
            return 54

        assert await backend.run_in_thread(thread) == 54

    @pytest.mark.feature_sniffio
    async def test____create_threads_portal____run_coroutine_from_thread____sniffio_contextvar_reset(
        self,
        backend: AsyncioBackend,
    ) -> None:
        import sniffio

        threads_portal = backend.create_threads_portal()
        sniffio.current_async_library_cvar.set("main")

        async def coroutine() -> str | None:
            return sniffio.current_async_library_cvar.get()

        def thread() -> str | None:
            return threads_portal.run_coroutine(coroutine)

        cvar_inner = await backend.run_in_thread(thread)
        cvar_outer = sniffio.current_async_library_cvar.get()

        assert cvar_inner == "asyncio"
        assert cvar_outer == "main"

    async def test____create_threads_portal____run_sync_from_thread_in_event_loop(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncioBackend,
    ) -> None:
        threads_portal = backend.create_threads_portal()

        def not_threadsafe_func(value: int) -> int:
            assert asyncio.get_running_loop() is event_loop
            return value

        with pytest.raises(RuntimeError):
            threads_portal.run_sync(not_threadsafe_func, 42)

        def thread() -> int:
            with pytest.raises(RuntimeError):
                asyncio.get_running_loop()
            return threads_portal.run_sync(not_threadsafe_func, 42)

        assert await backend.run_in_thread(thread) == 42

    async def test____create_threads_portal____run_sync_from_thread_in_event_loop____can_be_called_from_other_event_loop(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncioBackend,
    ) -> None:
        threads_portal = backend.create_threads_portal()

        def not_threadsafe_func(value: int) -> int:
            assert asyncio.get_running_loop() is event_loop
            return value

        def thread() -> int:
            async def main() -> int:
                assert asyncio.get_running_loop() is not event_loop
                return threads_portal.run_sync(not_threadsafe_func, 42)

            return asyncio.run(main())

        assert await backend.run_in_thread(thread) == 42

    async def test____create_threads_portal____run_sync_from_thread_in_event_loop____exception_raised(
        self,
        backend: AsyncioBackend,
    ) -> None:
        threads_portal = backend.create_threads_portal()
        expected_exception = OSError("Why not?")

        def not_threadsafe_func(value: int) -> int:
            raise expected_exception

        def thread() -> int:
            return threads_portal.run_sync(not_threadsafe_func, 42)

        with pytest.raises(OSError) as exc_info:
            await backend.run_in_thread(thread)

        assert exc_info.value is expected_exception

    async def test____create_threads_portal____run_sync_from_thread_in_event_loop____explicit_concurrent_future_Cancelled(
        self,
        backend: AsyncioBackend,
    ) -> None:
        threads_portal = backend.create_threads_portal()

        def not_threadsafe_func(value: int) -> int:
            raise FutureCancelledError()

        def thread() -> int:
            with pytest.raises(FutureCancelledError):
                return threads_portal.run_sync(not_threadsafe_func, 42)
            return 54

        assert await backend.run_in_thread(thread) == 54

    @pytest.mark.feature_sniffio
    async def test____create_threads_portal____run_sync_from_thread_in_event_loop____sniffio_contextvar_reset(
        self,
        backend: AsyncioBackend,
    ) -> None:
        import sniffio

        threads_portal = backend.create_threads_portal()
        sniffio.current_async_library_cvar.set("main")

        def callback() -> str | None:
            return sniffio.current_async_library_cvar.get()

        def thread() -> str | None:
            return threads_portal.run_sync(callback)

        cvar_inner = await backend.run_in_thread(thread)
        cvar_outer = sniffio.current_async_library_cvar.get()

        assert cvar_inner == "asyncio"
        assert cvar_outer == "main"
