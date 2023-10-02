from __future__ import annotations

import asyncio
import contextvars
import time
from collections.abc import Awaitable, Callable
from concurrent.futures import CancelledError as FutureCancelledError, Future, wait as wait_concurrent_futures
from contextlib import ExitStack
from typing import TYPE_CHECKING, Any, Literal

from easynetwork.api_async.backend.factory import AsyncBackendFactory
from easynetwork_asyncio.backend import AsyncIOBackend

import pytest

if TYPE_CHECKING:
    from unittest.mock import AsyncMock

    from pytest_mock import MockerFixture

cvar_for_test: contextvars.ContextVar[str] = contextvars.ContextVar("cvar_for_test", default="")


@pytest.mark.asyncio
class TestAsyncioBackend:
    @pytest.fixture
    @staticmethod
    def backend() -> AsyncIOBackend:
        backend = AsyncBackendFactory.new("asyncio")
        assert isinstance(backend, AsyncIOBackend)
        return backend

    async def test____use_asyncio_transport____True_by_default(self, backend: AsyncIOBackend) -> None:
        assert backend.using_asyncio_transport()

    async def test____cancel_shielded_coro_yield____mute_cancellation(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
    ) -> None:
        task: asyncio.Task[None] = event_loop.create_task(backend.cancel_shielded_coro_yield())

        await asyncio.sleep(0)

        for _ in range(3):
            task.cancel()

        await task
        assert not task.cancelled()
        assert task.cancelling() == 3

    @pytest.mark.parametrize("cancel_message", ["something", None], ids=lambda p: f"cancel_message=={p!r}")
    async def test____cancel_shielded_coro_yield____cancel_at_the_next_checkpoint(
        self,
        cancel_message: str | None,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
    ) -> None:
        test_list: list[str] = []

        async def coroutine() -> None:
            test_list.append("a")
            await backend.cancel_shielded_coro_yield()
            test_list.append("b")
            await backend.cancel_shielded_coro_yield()
            test_list.append("c")
            await backend.coro_yield()
            test_list.append("this should not be in the list")

        task: asyncio.Task[None] = event_loop.create_task(coroutine())

        await asyncio.sleep(0)

        for _ in range(3):
            task.cancel(msg=cancel_message)

        with pytest.raises(asyncio.CancelledError) as exc_info:
            await task
        assert task.cancelled()
        assert task.cancelling() == 3
        assert test_list == ["a", "b", "c"]
        if cancel_message is None:
            assert exc_info.value.args == ()
        else:
            assert exc_info.value.args == (cancel_message,)

    async def test____ignore_cancellation____always_continue_on_cancellation(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
    ) -> None:
        task: asyncio.Task[int] = event_loop.create_task(backend.ignore_cancellation(asyncio.sleep(0.5, 42)))

        for i in range(5):
            for _ in range(3):
                event_loop.call_later(0.1 * i, task.cancel)

        assert await task == 42
        assert not task.cancelled()
        assert task.cancelling() == 15

    async def test____ignore_cancellation____task_does_not_appear_in_registered_tasks(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
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
        backend: AsyncIOBackend,
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

    @pytest.mark.xfail("sys.version_info < (3, 12)", reason="asyncio.Task.get_context() does not exist before Python 3.12")
    async def test____ignore_cancellation____share_same_context_with_host_task(
        self,
        backend: AsyncIOBackend,
    ) -> None:
        async def coroutine() -> None:
            await asyncio.sleep(0.1)

            cvar_for_test.set("after_in_coroutine")

        cvar_for_test.set("before_in_current_task")
        await backend.ignore_cancellation(coroutine())

        assert cvar_for_test.get() == "after_in_coroutine"

    async def test____timeout____respected(
        self,
        backend: AsyncIOBackend,
    ) -> None:
        with backend.timeout(1):
            assert await asyncio.sleep(0.5, 42) == 42

    async def test____timeout____timeout_error(
        self,
        backend: AsyncIOBackend,
    ) -> None:
        with pytest.raises(TimeoutError):
            with backend.timeout(0.25):
                await asyncio.sleep(0.5, 42)

    async def test____timeout____cancellation(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
    ) -> None:
        async def coroutine() -> None:
            with backend.timeout(0.25):
                await asyncio.sleep(0.5, 42)

        task = event_loop.create_task(coroutine())
        event_loop.call_later(0.10, task.cancel)

        await asyncio.wait({task})
        assert task.cancelled()

    async def test____timeout_at____respected(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
    ) -> None:
        with backend.timeout_at(event_loop.time() + 1):
            assert await asyncio.sleep(0.5, 42) == 42

    async def test____timeout_at____timeout_error(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
    ) -> None:
        with pytest.raises(TimeoutError):
            with backend.timeout_at(event_loop.time() + 0.25):
                await asyncio.sleep(0.5, 42)

    async def test____timeout_at____cancellation(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
    ) -> None:
        async def coroutine() -> None:
            with backend.timeout_at(event_loop.time() + 0.25):
                await asyncio.sleep(0.5, 42)

        task = event_loop.create_task(coroutine())
        event_loop.call_later(0.10, task.cancel)

        await asyncio.wait({task})
        assert task.cancelled()

    async def test____move_on_after____respected(
        self,
        backend: AsyncIOBackend,
    ) -> None:
        with backend.move_on_after(1) as scope:
            assert await asyncio.sleep(0.5, 42) == 42

        assert not scope.cancelled_caught()

    async def test____move_on_after____timeout_error(
        self,
        backend: AsyncIOBackend,
    ) -> None:
        with backend.move_on_after(0.25) as scope:
            await asyncio.sleep(0.5, 42)

        assert scope.cancelled_caught()

    async def test____move_on_after____cancellation(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
    ) -> None:
        async def coroutine() -> None:
            with backend.move_on_after(0.25):
                await asyncio.sleep(0.5, 42)

        task = event_loop.create_task(coroutine())
        event_loop.call_later(0.10, task.cancel)

        await asyncio.wait({task})
        assert task.cancelled()

    async def test____move_on_at____respected(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
    ) -> None:
        with backend.move_on_at(event_loop.time() + 1) as scope:
            assert await asyncio.sleep(0.5, 42) == 42

        assert not scope.cancelled_caught()

    async def test____move_on_at____timeout_error(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
    ) -> None:
        with backend.move_on_at(event_loop.time() + 0.25) as scope:
            await asyncio.sleep(0.5, 42)

        assert scope.cancelled_caught()

    async def test____move_on_at____cancellation(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
    ) -> None:
        async def coroutine() -> None:
            with backend.move_on_at(event_loop.time() + 0.25):
                await asyncio.sleep(0.5, 42)

        task = event_loop.create_task(coroutine())
        event_loop.call_later(0.10, task.cancel)

        await asyncio.wait({task})
        assert task.cancelled()

    async def test____sleep_forever____sleep_until_cancellation(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
    ) -> None:
        sleep_task = event_loop.create_task(backend.sleep_forever())

        event_loop.call_later(0.5, sleep_task.cancel)

        with pytest.raises(asyncio.CancelledError):
            await sleep_task

    async def test____open_cancel_scope____unbound_cancel_scope____cancel_when_entering(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
    ) -> None:
        async def coroutine() -> None:
            current_task = asyncio.current_task()
            assert current_task is not None

            scope = backend.open_cancel_scope()
            scope.cancel()
            assert scope.cancel_called()

            assert current_task.cancelling() == 0
            await asyncio.sleep(0.1)

            with scope:
                assert current_task.cancelling() == 1
                scope.cancel()
                assert current_task.cancelling() == 1
                await backend.coro_yield()

            assert current_task.cancelling() == 0
            assert scope.cancelled_caught()

        await event_loop.create_task(coroutine())

    async def test____open_cancel_scope____unbound_cancel_scope____deadline_scheduled_when_entering(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
    ) -> None:
        async def coroutine() -> None:
            current_task = asyncio.current_task()
            assert current_task is not None

            scope = backend.open_cancel_scope()
            scope.reschedule(event_loop.time() + 1)

            assert current_task.cancelling() == 0
            await asyncio.sleep(0.5)

            with backend.timeout(0.6):
                with scope:
                    assert current_task.cancelling() == 0
                    await backend.sleep_forever()

            assert scope.cancelled_caught()

        await event_loop.create_task(coroutine())

    async def test____open_cancel_scope____overwrite_defined_deadline(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
    ) -> None:
        async def coroutine() -> None:
            current_task = asyncio.current_task()
            assert current_task is not None

            with backend.move_on_after(1) as scope:
                await backend.sleep(0.5)
                scope.deadline += 1
                await backend.sleep(1)
                del scope.deadline
                assert scope.deadline == float("+inf")
                await backend.sleep(1)

            assert not scope.cancelled_caught()

        await event_loop.create_task(coroutine())

    async def test____open_cancel_scope____invalid_deadline(
        self,
        backend: AsyncIOBackend,
    ) -> None:
        with pytest.raises(ValueError):
            _ = backend.open_cancel_scope(deadline=float("nan"))

    async def test____open_cancel_scope____context_reuse(
        self,
        backend: AsyncIOBackend,
    ) -> None:
        with backend.open_cancel_scope() as scope:
            with pytest.raises(RuntimeError, match=r"^CancelScope entered twice$"):
                with scope:
                    ...

        with pytest.raises(RuntimeError, match=r"^CancelScope entered twice$"):
            with scope:
                ...

    async def test____open_cancel_scope____context_exit_before_enter(
        self,
        backend: AsyncIOBackend,
    ) -> None:
        with pytest.raises(RuntimeError, match=r"^This cancel scope is not active$"), ExitStack() as stack:
            stack.push(backend.open_cancel_scope())

    async def test____open_cancel_scope____task_misnesting(
        self,
        backend: AsyncIOBackend,
    ) -> None:
        async def coroutine() -> ExitStack:
            stack = ExitStack()
            stack.enter_context(backend.open_cancel_scope())
            return stack

        stack = await asyncio.create_task(coroutine())
        with pytest.raises(RuntimeError, match=r"^Attempted to exit cancel scope in a different task than it was entered in$"):
            stack.close()

    async def test____open_cancel_scope____scope_misnesting(
        self,
        backend: AsyncIOBackend,
    ) -> None:
        stack = ExitStack()
        stack.enter_context(backend.open_cancel_scope())
        with backend.open_cancel_scope():
            with pytest.raises(
                RuntimeError, match=r"^Attempted to exit a cancel scope that isn't the current tasks's current cancel scope$"
            ):
                stack.close()
            stack.pop_all()

    async def test____create_task_group____task_pool(
        self,
        backend: AsyncIOBackend,
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
        backend: AsyncIOBackend,
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

    @pytest.mark.parametrize("join_method", ["join", "join_or_cancel"])
    async def test____create_task_group____task_join_cancel_shielding(
        self,
        join_method: Literal["join", "join_or_cancel"],
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
    ) -> None:
        async def coroutine(value: int) -> int:
            return await asyncio.sleep(0.5, value)

        async with backend.create_task_group() as task_group:
            inner_task = task_group.start_soon(coroutine, 42)

            match join_method:
                case "join":
                    outer_task = event_loop.create_task(inner_task.join())
                case "join_or_cancel":
                    outer_task = event_loop.create_task(inner_task.join_or_cancel())
                case _:
                    pytest.fail("invalid argument")
            event_loop.call_later(0.2, outer_task.cancel)

            with pytest.raises(asyncio.CancelledError):
                await outer_task

            assert outer_task.cancelled()
            if join_method == "join_or_cancel":
                assert inner_task.cancelled()
            else:
                assert not inner_task.cancelled()
                assert await inner_task.join() == 42

    async def test____create_task_group____start_soon_with_context(
        self,
        backend: AsyncIOBackend,
    ) -> None:
        async def coroutine(value: str) -> None:
            cvar_for_test.set(value)

        async with backend.create_task_group() as task_group:
            cvar_for_test.set("something")
            ctx = contextvars.copy_context()
            task = task_group.start_soon(coroutine, "other", context=ctx)
            await task.wait()
            assert cvar_for_test.get() == "something"
            assert ctx.run(cvar_for_test.get) == "other"

    async def test____wait_future____wait_until_done(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
    ) -> None:
        future: Future[int] = Future()
        event_loop.call_later(0.5, future.set_result, 42)

        assert await backend.wait_future(future) == 42

    @pytest.mark.parametrize("future_running", [None, "before", "after"], ids=lambda state: f"future_running=={state}")
    async def test____wait_future____cancel_future_if_task_is_cancelled(
        self,
        future_running: str | None,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
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
        backend: AsyncIOBackend,
    ) -> None:
        future: Future[int] = Future()
        task = event_loop.create_task(backend.wait_future(future))

        event_loop.call_later(0.1, future.cancel)
        await asyncio.wait([task])

        assert not task.cancelled()
        assert type(task.exception()) is FutureCancelledError

    async def test____wait_future____already_done(
        self,
        backend: AsyncIOBackend,
    ) -> None:
        future: Future[int] = Future()
        future.set_result(42)

        assert await backend.wait_future(future) == 42

    async def test____wait_future____already_cancelled(
        self,
        backend: AsyncIOBackend,
    ) -> None:
        future: Future[int] = Future()
        future.cancel()

        with pytest.raises(FutureCancelledError):
            await backend.wait_future(future)

    async def test____wait_future____already_cancelled____task_cancelled_too(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
    ) -> None:
        future: Future[int] = Future()
        future.cancel()

        task = event_loop.create_task(backend.wait_future(future))
        event_loop.call_soon(task.cancel)

        with pytest.raises(asyncio.CancelledError):
            await task

    async def test____wait_future____task_cancellation_prevails_over_future_cancellation(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
    ) -> None:
        future: Future[int] = Future()

        task = event_loop.create_task(backend.wait_future(future))

        event_loop.call_soon(future.cancel)
        for _ in range(3):
            await asyncio.sleep(0)
        event_loop.call_soon(task.cancel)

        with pytest.raises(asyncio.CancelledError):
            await task

        assert task.cancelled()

    async def test____run_in_thread____cannot_be_cancelled(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
    ) -> None:
        task = event_loop.create_task(backend.run_in_thread(time.sleep, 0.5))
        event_loop.call_later(0.1, task.cancel)
        event_loop.call_later(0.2, task.cancel)
        event_loop.call_later(0.3, task.cancel)
        event_loop.call_later(0.4, task.cancel)

        await task

        assert not task.cancelled()

    @pytest.mark.feature_sniffio
    async def test____run_in_thread____sniffio_contextvar_reset(self, backend: AsyncIOBackend) -> None:
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
        backend: AsyncIOBackend,
    ) -> None:
        threads_portal = backend.create_threads_portal()

        async def coroutine(value: int) -> int:
            assert asyncio.get_running_loop() is event_loop
            return await asyncio.sleep(0.5, value)

        def thread() -> int:
            with pytest.raises(RuntimeError):
                asyncio.get_running_loop()
            return threads_portal.run_coroutine(coroutine, 42)

        with pytest.raises(RuntimeError):
            await backend.run_in_thread(thread)

        async with threads_portal:
            with pytest.raises(RuntimeError):
                threads_portal.run_coroutine(coroutine, 42)

            assert await backend.run_in_thread(thread) == 42

        with pytest.raises(RuntimeError):
            await backend.run_in_thread(thread)

    async def test____create_threads_portal____run_coroutine_from_thread____can_be_called_from_other_event_loop(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
    ) -> None:
        async def coroutine(value: int) -> int:
            assert asyncio.get_running_loop() is event_loop
            return await asyncio.sleep(0.5, value)

        def thread() -> int:
            async def main() -> int:
                assert asyncio.get_running_loop() is not event_loop
                return threads_portal.run_coroutine(coroutine, 42)

            return backend.bootstrap(main)

        async with backend.create_threads_portal() as threads_portal:
            assert await backend.run_in_thread(thread) == 42

    async def test____create_threads_portal____run_coroutine_from_thread____exception_raised(
        self,
        backend: AsyncIOBackend,
    ) -> None:
        expected_exception = OSError("Why not?")

        async def coroutine(value: int) -> int:
            raise expected_exception

        def thread() -> int:
            return threads_portal.run_coroutine(coroutine, 42)

        async with backend.create_threads_portal() as threads_portal:
            with pytest.raises(OSError) as exc_info:
                await backend.run_in_thread(thread)

        assert exc_info.value is expected_exception

    async def test____create_threads_portal____run_coroutine_from_thread____coroutine_cancelled(
        self,
        backend: AsyncIOBackend,
    ) -> None:
        async def coroutine(value: int) -> int:
            task = asyncio.current_task()
            assert task is not None
            task.get_loop().call_later(0.5, task.cancel)
            await task.get_loop().create_future()
            raise AssertionError("Not cancelled")

        def thread() -> int:
            return threads_portal.run_coroutine(coroutine, 42)

        async with backend.create_threads_portal() as threads_portal:
            with pytest.raises(asyncio.CancelledError):  # asyncio do the job to convert the concurrent.futures.CancelledError
                await backend.run_in_thread(thread)

    async def test____create_threads_portal____run_coroutine_from_thread____explicit_concurrent_future_Cancelled(
        self,
        backend: AsyncIOBackend,
    ) -> None:
        async def coroutine(value: int) -> int:
            raise FutureCancelledError()

        def thread() -> int:
            with pytest.raises(FutureCancelledError):
                return threads_portal.run_coroutine(coroutine, 42)
            return 54

        async with backend.create_threads_portal() as threads_portal:
            assert await backend.run_in_thread(thread) == 54

    @pytest.mark.feature_sniffio
    async def test____create_threads_portal____run_coroutine_from_thread____sniffio_contextvar_reset(
        self,
        backend: AsyncIOBackend,
    ) -> None:
        import sniffio

        sniffio.current_async_library_cvar.set("main")

        async def coroutine() -> str | None:
            return sniffio.current_async_library_cvar.get()

        def thread() -> str | None:
            return threads_portal.run_coroutine(coroutine)

        async with backend.create_threads_portal() as threads_portal:
            cvar_inner = await backend.run_in_thread(thread)
            cvar_outer = sniffio.current_async_library_cvar.get()

        assert cvar_inner == "asyncio"
        assert cvar_outer == "main"

    async def test____create_threads_portal____run_sync_from_thread_in_event_loop(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
    ) -> None:
        threads_portal = backend.create_threads_portal()

        def not_threadsafe_func(value: int) -> int:
            assert asyncio.get_running_loop() is event_loop
            return value

        def thread() -> int:
            with pytest.raises(RuntimeError):
                asyncio.get_running_loop()
            return threads_portal.run_sync(not_threadsafe_func, 42)

        with pytest.raises(RuntimeError):
            await backend.run_in_thread(thread)

        async with threads_portal:
            with pytest.raises(RuntimeError):
                threads_portal.run_sync(not_threadsafe_func, 42)

            assert await backend.run_in_thread(thread) == 42

        with pytest.raises(RuntimeError):
            await backend.run_in_thread(thread)

    async def test____create_threads_portal____run_sync_from_thread_in_event_loop____can_be_called_from_other_event_loop(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
    ) -> None:
        def not_threadsafe_func(value: int) -> int:
            assert asyncio.get_running_loop() is event_loop
            return value

        def thread() -> int:
            async def main() -> int:
                assert asyncio.get_running_loop() is not event_loop
                return threads_portal.run_sync(not_threadsafe_func, 42)

            return backend.bootstrap(main)

        async with backend.create_threads_portal() as threads_portal:
            assert await backend.run_in_thread(thread) == 42

    async def test____create_threads_portal____run_sync_from_thread_in_event_loop____exception_raised(
        self,
        backend: AsyncIOBackend,
    ) -> None:
        expected_exception = OSError("Why not?")

        def not_threadsafe_func(value: int) -> int:
            raise expected_exception

        def thread() -> int:
            return threads_portal.run_sync(not_threadsafe_func, 42)

        async with backend.create_threads_portal() as threads_portal:
            with pytest.raises(OSError) as exc_info:
                await backend.run_in_thread(thread)

        assert exc_info.value is expected_exception

    async def test____create_threads_portal____run_sync_from_thread_in_event_loop____explicit_concurrent_future_Cancelled(
        self,
        backend: AsyncIOBackend,
    ) -> None:
        def not_threadsafe_func(value: int) -> int:
            raise FutureCancelledError()

        def thread() -> int:
            with pytest.raises(FutureCancelledError):
                return threads_portal.run_sync(not_threadsafe_func, 42)
            return 54

        async with backend.create_threads_portal() as threads_portal:
            assert await backend.run_in_thread(thread) == 54

    async def test____create_threads_portal____run_sync_from_thread_in_event_loop____async_function_given(
        self,
        backend: AsyncIOBackend,
    ) -> None:
        async def coroutine() -> None:
            raise AssertionError("Should not be called")

        def thread() -> None:
            with pytest.raises(TypeError, match=r"^func is a coroutine function.$") as exc_info:
                _ = threads_portal.run_sync(coroutine)

            assert exc_info.value.__notes__ == ["You should use run_coroutine() or run_coroutine_soon() instead."]

        async with backend.create_threads_portal() as threads_portal:
            await backend.run_in_thread(thread)

    @pytest.mark.feature_sniffio
    async def test____create_threads_portal____run_sync_from_thread_in_event_loop____sniffio_contextvar_reset(
        self,
        backend: AsyncIOBackend,
    ) -> None:
        import sniffio

        sniffio.current_async_library_cvar.set("main")

        def callback() -> str | None:
            return sniffio.current_async_library_cvar.get()

        def thread() -> str | None:
            return threads_portal.run_sync(callback)

        async with backend.create_threads_portal() as threads_portal:
            cvar_inner = await backend.run_in_thread(thread)
            cvar_outer = sniffio.current_async_library_cvar.get()

        assert cvar_inner == "asyncio"
        assert cvar_outer == "main"

    async def test____create_threads_portal____run_sync_soon____future_cancelled_before_call(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
        mocker: MockerFixture,
    ) -> None:
        func_stub = mocker.stub()

        def thread() -> None:
            event_loop.call_soon_threadsafe(time.sleep, 1)  # Drastically slow down event loop

            future = threads_portal.run_sync_soon(func_stub, 42)

            with pytest.raises(TimeoutError):
                future.exception(timeout=0.2)

            future.cancel()
            wait_concurrent_futures({future}, timeout=5)  # Test if future.set_running_or_notify_cancel() have been called
            assert future.cancelled()

        async with backend.create_threads_portal() as threads_portal:
            await backend.run_in_thread(thread)

        func_stub.assert_not_called()

    async def test____create_threads_portal____run_coroutine_soon____future_cancelled(
        self,
        backend: AsyncIOBackend,
    ) -> None:
        def thread() -> None:
            future = threads_portal.run_coroutine_soon(asyncio.sleep, 1)

            with pytest.raises(TimeoutError):
                future.exception(timeout=0.2)

            future.cancel()
            wait_concurrent_futures({future}, timeout=0.2)  # Test if future.set_running_or_notify_cancel() have been called
            assert future.cancelled()

        async with backend.create_threads_portal() as threads_portal:
            await backend.run_in_thread(thread)

    @pytest.mark.parametrize("value", [42, ValueError("Not caught")], ids=repr)
    async def test____create_threads_portal____run_coroutine_soon____future_cancelled____cancellation_ignored(
        self,
        value: int | Exception,
        backend: AsyncIOBackend,
        mocker: MockerFixture,
    ) -> None:
        cancellation_ignored = mocker.stub()

        async def coroutine() -> int:
            try:
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                pass
            await asyncio.sleep(0)
            cancellation_ignored()
            if isinstance(value, Exception):
                raise value
            return value

        def thread() -> None:
            future = threads_portal.run_coroutine_soon(coroutine)

            with pytest.raises(TimeoutError):
                future.exception(timeout=0.2)

            future.cancel()
            wait_concurrent_futures({future}, timeout=0.2)  # Test if future.set_running_or_notify_cancel() have been called
            assert future.cancelled()

        async with backend.create_threads_portal() as threads_portal:
            await backend.run_in_thread(thread)

        cancellation_ignored.assert_called_once()

    async def test____create_threads_portal____context_exit____wait_scheduled_call_soon(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
        mocker: MockerFixture,
    ) -> None:
        func_stub = mocker.stub()
        func_stub.return_value = "Hello, world!"

        def thread() -> None:
            future = threads_portal.run_sync_soon(func_stub, 42)
            assert future.result(timeout=1) == "Hello, world!"

        async with backend.create_threads_portal() as threads_portal:
            task = event_loop.create_task(backend.run_in_thread(thread))
            event_loop.call_soon(time.sleep, 0.5)
            await asyncio.sleep(0)

        func_stub.assert_called_once_with(42)
        await task

    async def test____create_threads_portal____context_exit____wait_scheduled_call_soon_for_coroutine(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
        mocker: MockerFixture,
    ) -> None:
        coro_stub: AsyncMock = mocker.async_stub()
        coro_stub.return_value = "Hello, world!"

        def thread() -> None:
            future = threads_portal.run_coroutine_soon(coro_stub, 42)
            assert future.result(timeout=1) == "Hello, world!"

        async with backend.create_threads_portal() as threads_portal:
            task = event_loop.create_task(backend.run_in_thread(thread))
            event_loop.call_soon(time.sleep, 0.5)
            await asyncio.sleep(0)

        coro_stub.assert_awaited_once_with(42)
        await task

    async def test____create_threads_portal____entered_twice(
        self,
        backend: AsyncIOBackend,
    ) -> None:
        async with backend.create_threads_portal() as threads_portal:
            with pytest.raises(RuntimeError, match=r"ThreadsPortal entered twice\."):
                await threads_portal.__aenter__()


@pytest.mark.asyncio
class TestAsyncioBackendShieldedCancellation:
    @pytest.fixture
    @staticmethod
    def backend() -> AsyncIOBackend:
        backend = AsyncBackendFactory.new("asyncio")
        assert isinstance(backend, AsyncIOBackend)
        return backend

    @pytest.fixture(params=["cancel_shielded_coro_yield", "ignore_cancellation", "run_in_thread", "wait_future"])
    @staticmethod
    def cancel_shielded_coroutine(
        request: pytest.FixtureRequest,
        backend: AsyncIOBackend,
        event_loop: asyncio.AbstractEventLoop,
    ) -> Callable[[], Awaitable[Any]]:
        match getattr(request, "param"):
            case "cancel_shielded_coro_yield":
                return backend.cancel_shielded_coro_yield
            case "ignore_cancellation":
                return lambda: backend.ignore_cancellation(backend.sleep(0.1))
            case "run_in_thread":
                return lambda: backend.run_in_thread(time.sleep, 0.1)
            case "wait_future":

                async def wait_future_coroutine() -> None:
                    future: Future[None] = Future()
                    future.set_running_or_notify_cancel()
                    event_loop.call_later(0.1, future.set_result, None)
                    return await backend.wait_future(future)

                return wait_future_coroutine
            case _:
                pytest.fail("Invalid parameter")

    async def test____cancel_shielded_coroutine____do_not_cancel_at_timeout_end(
        self,
        cancel_shielded_coroutine: Callable[[], Awaitable[Any]],
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
    ) -> None:
        checkpoints: list[str] = []

        async def coroutine(value: int) -> int:
            with backend.timeout(0) as scope:
                await cancel_shielded_coroutine()
                checkpoints.append("cancel_shielded_coroutine")

            assert scope.cancel_called()
            assert not scope.cancelled_caught()
            await backend.coro_yield()
            checkpoints.append("coro_yield")
            return value

        task = event_loop.create_task(coroutine(42))

        assert await task == 42
        assert checkpoints == ["cancel_shielded_coroutine", "coro_yield"]

    async def test____cancel_shielded_coroutine____cancel_at_timeout_end_if_nested(
        self,
        cancel_shielded_coroutine: Callable[[], Awaitable[Any]],
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
    ) -> None:
        checkpoints: list[str] = []

        async def coroutine(value: int) -> int:
            current_task = asyncio.current_task()
            assert current_task is not None

            with backend.move_on_after(0) as scope:
                with backend.timeout(0):
                    with backend.timeout(0):
                        await cancel_shielded_coroutine()
                        checkpoints.append("inner_cancel_shielded_coroutine")
                        assert current_task.cancelling() == 3

                    await cancel_shielded_coroutine()
                    assert current_task.cancelling() == 2
                    checkpoints.append("cancel_shielded_coroutine")

                assert current_task.cancelling() == 1
                checkpoints.append("inner_coro_yield")
                await backend.coro_yield()
                checkpoints.append("should_not_be_here")

            assert current_task.cancelling() == 0

            assert scope.cancel_called()
            assert scope.cancelled_caught()
            await backend.coro_yield()
            checkpoints.append("coro_yield")
            return value

        task = event_loop.create_task(coroutine(42))

        assert await task == 42
        assert checkpoints == ["inner_cancel_shielded_coroutine", "cancel_shielded_coroutine", "inner_coro_yield", "coro_yield"]

    async def test____timeout____cancel_at_timeout_end_if_task_cancellation_were_already_delayed(
        self,
        cancel_shielded_coroutine: Callable[[], Awaitable[Any]],
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
    ) -> None:
        checkpoints: list[str] = []

        async def coroutine(value: int) -> int:
            current_task = asyncio.current_task()
            assert current_task is not None

            await cancel_shielded_coroutine()
            checkpoints.append("cancel_shielded_coroutine")

            with backend.timeout(0), backend.open_cancel_scope():
                await cancel_shielded_coroutine()
                checkpoints.append("inner_cancel_shielded_coroutine")
                assert current_task.cancelling() == 2

            assert current_task.cancelling() == 1
            await backend.coro_yield()
            checkpoints.append("should_not_be_here")
            return value

        task = event_loop.create_task(coroutine(42))
        event_loop.call_soon(task.cancel)

        with pytest.raises(asyncio.CancelledError):
            await task
        assert checkpoints == ["cancel_shielded_coroutine", "inner_cancel_shielded_coroutine"]

    async def test____cancel_shielded_coroutine____cancel_at_timeout_end_if_task_cancellation_does_not_come_from_scope(
        self,
        cancel_shielded_coroutine: Callable[[], Awaitable[Any]],
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
    ) -> None:
        checkpoints: list[str] = []

        async def coroutine(value: int) -> int:
            current_task = asyncio.current_task()
            assert current_task is not None

            with backend.open_cancel_scope():
                with backend.open_cancel_scope():
                    await cancel_shielded_coroutine()
                    checkpoints.append("cancel_shielded_coroutine")
                    assert current_task.cancelling() == 1

            assert current_task.cancelling() == 1
            await backend.coro_yield()
            checkpoints.append("should_not_be_here")
            return value

        task = event_loop.create_task(coroutine(42))
        event_loop.call_soon(task.cancel)

        with pytest.raises(asyncio.CancelledError):
            await task
        assert checkpoints == ["cancel_shielded_coroutine"]

    async def test____cancel_shielded_coroutine____scope_cancellation_edge_case_1(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
    ) -> None:
        async def coroutine() -> None:
            current_task = asyncio.current_task()
            assert current_task is not None

            inner_scope = backend.open_cancel_scope()
            with backend.move_on_after(0.5) as outer_scope:
                with inner_scope:
                    await backend.ignore_cancellation(backend.sleep(1))
                    inner_scope.cancel()
                    await backend.coro_yield()

            assert outer_scope.cancel_called()
            assert inner_scope.cancel_called()

            assert not outer_scope.cancelled_caught()
            assert inner_scope.cancelled_caught()

        await event_loop.create_task(coroutine())

    async def test____cancel_shielded_coroutine____scope_cancellation_edge_case_2(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
    ) -> None:
        async def coroutine() -> None:
            current_task = asyncio.current_task()
            assert current_task is not None

            outer_scope = backend.move_on_after(1.5)
            inner_scope = backend.move_on_after(0.5)
            with outer_scope:
                with backend.open_cancel_scope(), backend.open_cancel_scope():
                    with inner_scope:
                        await backend.ignore_cancellation(backend.sleep(1))
                assert not inner_scope.cancelled_caught()
                try:
                    await backend.coro_yield()
                except asyncio.CancelledError:
                    pytest.fail("Cancelled")
                await backend.sleep(1)

            assert outer_scope.cancel_called()
            assert inner_scope.cancel_called()

            assert outer_scope.cancelled_caught()
            assert not inner_scope.cancelled_caught()

        await event_loop.create_task(coroutine())

    async def test____cancel_shielded_coroutine____scope_cancellation_edge_case_3(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
    ) -> None:
        async def coroutine() -> None:
            current_task = asyncio.current_task()
            assert current_task is not None

            with backend.move_on_after(0) as inner_scope:
                pass

            await backend.coro_yield()

            assert not inner_scope.cancel_called()

            assert not inner_scope.cancelled_caught()

        await event_loop.create_task(coroutine())

    @pytest.mark.xfail(raises=asyncio.CancelledError, reason="Task.cancel() cannot be erased", strict=True)
    async def test____cancel_shielded_coroutine____scope_cancellation_edge_case_4(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
    ) -> None:
        async def coroutine() -> None:
            current_task = asyncio.current_task()
            assert current_task is not None

            with backend.open_cancel_scope() as inner_scope:
                inner_scope.cancel()

            await backend.coro_yield()

            assert inner_scope.cancel_called()

            assert not inner_scope.cancelled_caught()

        await event_loop.create_task(coroutine())

    async def test____cancel_shielded_coroutine____scope_cancellation_edge_case_5(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
    ) -> None:
        async def coroutine() -> None:
            current_task = asyncio.current_task()
            assert current_task is not None

            outer_scope = backend.open_cancel_scope()
            inner_scope = backend.open_cancel_scope()
            with outer_scope:
                outer_scope.cancel()

                await backend.ignore_cancellation(backend.sleep(0.1))

                with inner_scope:
                    inner_scope.cancel()

                await backend.coro_yield()

            await backend.coro_yield()

            assert outer_scope.cancel_called()
            assert inner_scope.cancel_called()

            assert not inner_scope.cancelled_caught()
            assert outer_scope.cancelled_caught()

        await event_loop.create_task(coroutine())

    async def test____cancel_shielded_coroutine____scope_cancellation_edge_case_6(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
    ) -> None:
        async def coroutine() -> None:
            current_task = asyncio.current_task()
            assert current_task is not None

            outer_scope = backend.open_cancel_scope()
            inner_scope = backend.open_cancel_scope()
            with outer_scope:
                with inner_scope:
                    inner_scope.cancel()

                    await backend.cancel_shielded_coro_yield()

                    outer_scope.cancel()

                    await backend.cancel_shielded_coro_yield()

                await backend.coro_yield()

            await backend.coro_yield()

            assert outer_scope.cancel_called()
            assert inner_scope.cancel_called()

            assert not inner_scope.cancelled_caught()
            assert outer_scope.cancelled_caught()

        await event_loop.create_task(coroutine())

    async def test____ignore_cancellation____do_not_reschedule_if_inner_task_cancelled_itself(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
    ) -> None:
        async def self_cancellation() -> None:
            task = asyncio.current_task()
            assert task is not None
            event_loop.call_later(0.5, task.cancel)
            await backend.sleep_forever()

        checkpoints: list[str] = []

        async def coroutine() -> None:
            try:
                await backend.ignore_cancellation(self_cancellation())
            except asyncio.CancelledError:
                await asyncio.sleep(0)
                checkpoints.append("inner_yield_in_cancel")
                raise

        task = event_loop.create_task(coroutine())
        event_loop.call_soon(task.cancel)

        with pytest.raises(asyncio.CancelledError):
            await task

        assert checkpoints == ["inner_yield_in_cancel"]
