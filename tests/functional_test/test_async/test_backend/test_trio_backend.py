from __future__ import annotations

import concurrent.futures
import contextlib
import time
from typing import TYPE_CHECKING, Literal

from easynetwork.lowlevel.api_async.backend.abc import AsyncBackend, Task, TaskInfo
from easynetwork.lowlevel.api_async.backend.utils import new_builtin_backend

import pytest
import sniffio

from ....tools import call_later_with_nursery

if TYPE_CHECKING:
    from trio import Nursery

    from pytest_mock import MockerFixture


@pytest.mark.feature_trio
class TestTrioBackendBootstrap:
    @pytest.fixture(scope="class")
    @staticmethod
    def backend() -> AsyncBackend:
        return new_builtin_backend("trio")

    def test____bootstrap____sniffio_thread_local_reset(
        self,
        backend: AsyncBackend,
    ) -> None:
        assert sniffio.thread_local.name is None

        async def main() -> str | None:
            return sniffio.thread_local.name

        thread_local_inner = backend.bootstrap(main)

        assert thread_local_inner == "trio"
        assert sniffio.thread_local.name is None


@pytest.mark.feature_trio(async_test_auto_mark=True)
@pytest.mark.flaky(retries=3, delay=0.1)
class TestTrioBackend:

    @pytest.fixture(scope="class")
    @staticmethod
    def backend() -> AsyncBackend:
        return new_builtin_backend("trio")

    async def test____cancel_shielded_coro_yield____mute_cancellation(
        self,
        backend: AsyncBackend,
    ) -> None:
        import trio

        with trio.CancelScope() as scope:
            scope.cancel()
            await backend.cancel_shielded_coro_yield()

        assert not scope.cancelled_caught

    async def test____ignore_cancellation____always_continue_on_cancellation(
        self,
        backend: AsyncBackend,
    ) -> None:
        import trio

        checkpoints: list[int] = []

        async def coroutine() -> int:
            for i in range(2):
                await trio.sleep(0.25)
                checkpoints.append(i)
            return 42

        value: int = 0
        with trio.CancelScope() as scope:
            scope.cancel()
            value = await backend.ignore_cancellation(coroutine())

        assert not scope.cancelled_caught
        assert value == 42

    async def test____ignore_cancellation____runs_in_current_task(
        self,
        backend: AsyncBackend,
    ) -> None:
        import trio

        async def coroutine() -> trio.lowlevel.Task:
            return trio.lowlevel.current_task()

        assert (await backend.ignore_cancellation(coroutine())) is trio.lowlevel.current_task()

    async def test____timeout____respected(
        self,
        backend: AsyncBackend,
    ) -> None:
        import trio

        with backend.timeout(1):
            await trio.sleep(0.5)

    async def test____timeout____timeout_error(
        self,
        backend: AsyncBackend,
    ) -> None:
        import trio

        with pytest.raises(TimeoutError):
            with backend.timeout(0.25):
                await trio.sleep(0.5)

    async def test____timeout____cancellation(
        self,
        backend: AsyncBackend,
    ) -> None:
        import trio

        with trio.move_on_after(0.10) as root_scope:
            with backend.timeout(0.25):
                await trio.sleep(0.5)

        assert root_scope.cancelled_caught

    async def test____timeout_at____respected(
        self,
        backend: AsyncBackend,
    ) -> None:
        import trio

        with backend.timeout_at(trio.current_time() + 1):
            await trio.sleep(0.5)

    async def test____timeout_at____timeout_error(
        self,
        backend: AsyncBackend,
    ) -> None:
        import trio

        with pytest.raises(TimeoutError):
            with backend.timeout_at(trio.current_time() + 0.25):
                await trio.sleep(0.5)

    async def test____timeout_at____cancellation(
        self,
        backend: AsyncBackend,
    ) -> None:
        import trio

        with trio.move_on_after(0.10) as root_scope:
            with backend.timeout_at(trio.current_time() + 0.25):
                await trio.sleep(0.5)

        assert root_scope.cancelled_caught

    async def test____move_on_after____respected(
        self,
        backend: AsyncBackend,
    ) -> None:
        import trio

        with backend.move_on_after(1) as scope:
            await trio.sleep(0.5)

        assert not scope.cancelled_caught()

    async def test____move_on_after____timeout_error(
        self,
        backend: AsyncBackend,
    ) -> None:
        import trio

        with backend.move_on_after(0.25) as scope:
            await trio.sleep(0.5)

        assert scope.cancelled_caught()

    async def test____move_on_after____cancellation(
        self,
        backend: AsyncBackend,
    ) -> None:
        import trio

        with trio.move_on_after(0.10) as root_scope:
            with backend.move_on_after(0.25) as inner_scope:
                await trio.sleep(0.5)

        assert not inner_scope.cancelled_caught()
        assert root_scope.cancelled_caught

    async def test____move_on_at____respected(
        self,
        backend: AsyncBackend,
    ) -> None:
        import trio

        with backend.move_on_at(trio.current_time() + 1) as scope:
            await trio.sleep(0.5)

        assert not scope.cancelled_caught()

    async def test____move_on_at____timeout_error(
        self,
        backend: AsyncBackend,
    ) -> None:
        import trio

        with backend.move_on_at(trio.current_time() + 0.25) as scope:
            await trio.sleep(0.5)

        assert scope.cancelled_caught()

    async def test____move_on_at____cancellation(
        self,
        backend: AsyncBackend,
    ) -> None:
        import trio

        with trio.move_on_after(0.10) as root_scope:
            with backend.move_on_at(trio.current_time() + 0.25) as inner_scope:
                await trio.sleep(0.5)

        assert not inner_scope.cancelled_caught()
        assert root_scope.cancelled_caught

    async def test____sleep_forever____sleep_until_cancellation(
        self,
        backend: AsyncBackend,
    ) -> None:
        import trio

        with trio.move_on_after(0.5):
            await backend.sleep_forever()

    async def test____open_cancel_scope____unbound_cancel_scope____cancel_when_entering(
        self,
        backend: AsyncBackend,
    ) -> None:
        scope = backend.open_cancel_scope()
        scope.cancel()
        assert scope.cancel_called()

        await backend.sleep(0.1)

        with scope:
            scope.cancel()
            await backend.coro_yield()

        assert scope.cancelled_caught()

    async def test____open_cancel_scope____overwrite_defined_deadline(
        self,
        backend: AsyncBackend,
    ) -> None:
        with backend.move_on_after(1) as scope:
            await backend.sleep(0.5)
            scope.deadline += 1
            await backend.sleep(1)
            del scope.deadline
            assert scope.deadline == float("+inf")
            await backend.sleep(1)

        assert not scope.cancelled_caught()

    async def test____open_cancel_scope____invalid_deadline(
        self,
        backend: AsyncBackend,
    ) -> None:
        with pytest.raises(ValueError):
            _ = backend.open_cancel_scope(deadline=float("nan"))

    async def test____gather____no_parameters(
        self,
        backend: AsyncBackend,
    ) -> None:
        result: list[int] = await backend.gather()
        assert result == []

    async def test____gather____concurrent_await(
        self,
        backend: AsyncBackend,
    ) -> None:
        import trio

        async def coroutine(value: int) -> int:
            await trio.sleep(0.5)
            return value

        with backend.timeout(0.6):
            result = await backend.gather(
                coroutine(42),
                coroutine(54),
            )

        assert result == [42, 54]

    async def test____gather____concurrent_await____exception_raises(
        self,
        backend: AsyncBackend,
    ) -> None:
        import trio

        async def coroutine(value: int) -> int:
            with trio.CancelScope(shield=True):
                await trio.sleep(0.5)
            return value

        async def coroutine_error(exception: Exception) -> int:
            with trio.CancelScope(shield=True):
                await trio.sleep(0.5)
            raise exception

        with pytest.raises(ExceptionGroup) as exc_info:
            await backend.gather(
                coroutine(42),
                coroutine_error(ValueError("conversion error")),
                coroutine(54),
                coroutine_error(KeyError("unknown")),
            )

        assert len(exc_info.value.exceptions) == 2
        assert exc_info.group_contains(ValueError, depth=1)
        assert exc_info.group_contains(KeyError, depth=1)

    async def test____gather____duplicate_awaitable(
        self,
        backend: AsyncBackend,
        mocker: MockerFixture,
    ) -> None:
        import trio

        awaited = mocker.async_stub()

        async def coroutine(value: int) -> int:
            await awaited()
            await trio.sleep(0.5)
            return value

        awaitable = coroutine(42)

        result = await backend.gather(awaitable, awaitable, awaitable)

        assert result == [42, 42, 42]
        awaited.assert_awaited_once()

    async def test____create_task_group____start_soon(
        self,
        backend: AsyncBackend,
    ) -> None:
        import trio

        tasks: list[TaskInfo] = []

        async def coroutine(value: int) -> int:
            tasks.append(backend.get_current_task())
            await trio.sleep(0.5)
            return value

        async with backend.create_task_group() as tg:
            tg.start_soon(coroutine, 42)
            tg.start_soon(coroutine, 54)
            await trio.lowlevel.checkpoint()

        assert len(tasks) == 2

    async def test____create_task_group____start_soon____not_entered(
        self,
        backend: AsyncBackend,
    ) -> None:
        import trio

        tasks: list[TaskInfo] = []

        async def coroutine(value: int) -> int:
            tasks.append(backend.get_current_task())
            await trio.sleep(0.5)
            return value

        tg = backend.create_task_group()
        with pytest.raises(RuntimeError, match=r"^TaskGroup not started$"):
            tg.start_soon(coroutine, 42)
        with pytest.raises(RuntimeError, match=r"^TaskGroup not started$"):
            tg.start_soon(coroutine, 54)

        await trio.sleep(0.5)

        assert len(tasks) == 0

    async def test____create_task_group____start_soon____set_name(
        self,
        backend: AsyncBackend,
    ) -> None:
        import trio

        tasks: list[TaskInfo] = []

        async def coroutine(value: int) -> int:
            tasks.append(backend.get_current_task())
            await trio.sleep(0.5)
            return value

        async with backend.create_task_group() as tg:
            tg.start_soon(coroutine, 42, name="compute 42")
            tg.start_soon(coroutine, 54, name="compute 54")
            await trio.lowlevel.checkpoint()

        assert sorted(t.name for t in tasks) == ["compute 42", "compute 54"]

    async def test____create_task_group____start_and_wait(
        self,
        backend: AsyncBackend,
    ) -> None:
        import trio

        tasks: list[TaskInfo] = []

        async def coroutine(value: int) -> int:
            tasks.append(backend.get_current_task())
            await trio.sleep(0.5)
            return value

        async with backend.create_task_group() as tg:
            task_42 = await tg.start(coroutine, 42)
            task_54 = await tg.start(coroutine, 54)

            assert len(tasks) == 2
            assert tasks == [task_42.info, task_54.info]
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
        assert await task_42.join_or_cancel() == 42
        assert await task_54.join_or_cancel() == 54

    async def test____create_task_group____start_and_wait____not_entered(
        self,
        backend: AsyncBackend,
    ) -> None:
        import trio

        tasks: list[TaskInfo] = []

        async def coroutine(value: int) -> int:
            tasks.append(backend.get_current_task())
            await trio.sleep(0.5)
            return value

        tg = backend.create_task_group()
        with pytest.raises(RuntimeError, match=r"^TaskGroup not started$"):
            await tg.start(coroutine, 42)
        with pytest.raises(RuntimeError, match=r"^TaskGroup not started$"):
            await tg.start(coroutine, 54)

        await trio.sleep(0.5)

        assert len(tasks) == 0

    async def test____create_task_group____start_and_wait____set_name(
        self,
        backend: AsyncBackend,
    ) -> None:
        import trio

        async def coroutine(value: int) -> int:
            await trio.sleep(0.5)
            return value

        async with backend.create_task_group() as tg:
            task_42 = await tg.start(coroutine, 42, name="compute 42")
            task_54 = await tg.start(coroutine, 54, name="compute 54")

            assert task_42.info.name == "compute 42"
            assert task_54.info.name == "compute 54"

    async def test____create_task_group____task_cancellation(
        self,
        backend: AsyncBackend,
    ) -> None:
        import trio

        async def coroutine(value: int) -> int:
            await trio.sleep(0.5)
            return value

        async with backend.create_task_group() as tg:
            task_42 = await tg.start(coroutine, 42)
            task_54 = await tg.start(coroutine, 54)

            await trio.lowlevel.checkpoint()
            assert not task_42.done()
            assert not task_54.done()

            assert task_42.cancel()

        assert task_42.done()
        assert task_54.done()
        assert task_42.cancelled()
        assert not task_54.cancelled()
        with pytest.raises(trio.Cancelled):
            await task_42.join()
        assert await task_54.join() == 54

        # Tasks cannot be cancelled twice
        assert not task_42.cancel()

        # We can unwrap twice or more
        with pytest.raises(trio.Cancelled):
            await task_42.join()

    @pytest.mark.parametrize("join_method", ["join", "join_or_cancel", "wait"])
    async def test____create_task_group____task_join_cancel_shielding(
        self,
        join_method: Literal["join", "join_or_cancel", "wait"],
        backend: AsyncBackend,
        nursery: Nursery,
    ) -> None:
        import trio

        async def coroutine(value: int) -> int:
            await trio.sleep(0.5)
            return value

        async with backend.create_task_group() as task_group:
            inner_task = await task_group.start(coroutine, 42)

            with trio.CancelScope() as outer_scope:
                call_later_with_nursery(nursery, 0.2, outer_scope.cancel)

                match join_method:
                    case "join":
                        await inner_task.join()
                    case "join_or_cancel":
                        await inner_task.join_or_cancel()
                    case "wait":
                        await inner_task.wait()
                    case _:
                        pytest.fail("invalid argument")

            assert outer_scope.cancelled_caught
            if join_method == "join_or_cancel":
                assert inner_task.cancelled()
            else:
                assert not inner_task.cancelled()
                assert await inner_task.join() == 42

    async def test____create_task_group____task_join_erase_cancel(
        self,
        backend: AsyncBackend,
        nursery: Nursery,
    ) -> None:
        import trio

        async def coroutine(value: int) -> int:
            with contextlib.suppress(trio.Cancelled):
                await trio.sleep(0.5)
            return value

        async with backend.create_task_group() as task_group:
            inner_task = await task_group.start(coroutine, 42)

            with trio.CancelScope() as outer_scope:
                call_later_with_nursery(nursery, 0.1, outer_scope.cancel)

                await inner_task.join_or_cancel()

            assert outer_scope.cancel_called
            assert not outer_scope.cancelled_caught
            assert not inner_task.cancelled()
            assert await inner_task.join() == 42

    @pytest.mark.parametrize("task_state", ["result", "exception", "cancelled"])
    async def test____create_task_group____task_wait(
        self,
        task_state: Literal["result", "exception", "cancelled"],
        backend: AsyncBackend,
        nursery: Nursery,
    ) -> None:
        import outcome
        import trio

        tx, rx = trio.open_memory_channel[outcome.Outcome[None]](1)

        class FutureException(Exception):
            pass

        def set_future_result(task: Task[None]) -> None:
            with contextlib.closing(tx):
                match task_state:
                    case "result":
                        tx.send_nowait(outcome.Value(None))
                    case "exception":
                        tx.send_nowait(outcome.Error(FutureException("Error")))
                    case "cancelled":
                        task.cancel()
                    case _:
                        pytest.fail("invalid argument")

        async def coroutine() -> None:
            async with rx:
                return (await rx.receive()).unwrap()

        with pytest.raises(ExceptionGroup) if task_state == "exception" else contextlib.nullcontext() as exc_info:
            async with backend.create_task_group() as task_group:
                task = await task_group.start(coroutine)

                call_later_with_nursery(nursery, 0.1, set_future_result, task)

                await task.wait()
                assert task.done()

                # Must not yield if task is already done
                with backend.timeout(0):
                    await task.wait()

        if exc_info is not None:
            assert exc_info.group_contains(FutureException, depth=1)

    async def test____run_in_thread____cannot_be_cancelled_by_default(
        self,
        backend: AsyncBackend,
        nursery: Nursery,
    ) -> None:
        import trio

        with trio.CancelScope() as scope:
            call_later_with_nursery(nursery, 0.1, scope.cancel)
            call_later_with_nursery(nursery, 0.2, scope.cancel)
            call_later_with_nursery(nursery, 0.3, scope.cancel)
            call_later_with_nursery(nursery, 0.4, scope.cancel)
            await backend.run_in_thread(time.sleep, 0.5)

        assert not scope.cancelled_caught

    async def test____create_task_group____do_not_wrap_exception_from_within_context(
        self,
        backend: AsyncBackend,
    ) -> None:
        import trio

        async def coroutine(value: int) -> int:
            with trio.CancelScope(shield=True):
                await trio.sleep(0.5)
            return value

        with pytest.raises(ValueError, match=r"^unwrapped exception$"):
            async with backend.create_task_group() as task_group:
                task_group.start_soon(coroutine, 42)
                task_group.start_soon(coroutine, 54)
                await backend.coro_yield()
                raise ValueError("unwrapped exception")

    async def test____run_in_thread____abandon_on_cancel(
        self,
        backend: AsyncBackend,
    ) -> None:
        import trio

        with trio.move_on_after(0.1) as scope:
            await backend.run_in_thread(time.sleep, 0.5, abandon_on_cancel=True)

        assert scope.cancelled_caught

    async def test____run_in_thread____sniffio_contextvar_reset(self, backend: AsyncBackend) -> None:
        sniffio.current_async_library_cvar.set("trio")

        def callback() -> str | None:
            return sniffio.current_async_library_cvar.get()

        cvar_inner = await backend.run_in_thread(callback)
        cvar_outer = sniffio.current_async_library_cvar.get()

        assert cvar_inner is None
        assert cvar_outer == "trio"

    async def test____create_threads_portal____run_coroutine_from_thread(
        self,
        backend: AsyncBackend,
    ) -> None:
        import trio

        trio_token = trio.lowlevel.current_trio_token()
        threads_portal = backend.create_threads_portal()

        async def coroutine(value: int) -> int:
            assert trio.lowlevel.current_trio_token() is trio_token
            await trio.sleep(0.5)
            return value

        def thread() -> int:
            with pytest.raises(RuntimeError):
                trio.lowlevel.current_trio_token()
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
        backend: AsyncBackend,
    ) -> None:
        import trio

        trio_token = trio.lowlevel.current_trio_token()
        threads_portal = backend.create_threads_portal()

        async def coroutine(value: int) -> int:
            assert trio.lowlevel.current_trio_token() is trio_token
            await trio.sleep(0.5)
            return value

        def thread() -> int:
            async def main() -> int:
                assert trio.lowlevel.current_trio_token() is not trio_token
                return threads_portal.run_coroutine(coroutine, 42)

            return trio.run(main)

        async with backend.create_threads_portal() as threads_portal:
            assert await backend.run_in_thread(thread) == 42

    async def test____create_threads_portal____run_coroutine_from_thread____coroutine_cancelled(
        self,
        backend: AsyncBackend,
    ) -> None:
        import outcome
        import trio

        async def coroutine(value: int) -> int:
            with trio.move_on_after(0.5):
                result = await outcome.acapture(backend.sleep_forever)
            result.unwrap()
            raise AssertionError("Not cancelled")

        def thread() -> int:
            return threads_portal.run_coroutine(coroutine, 42)

        async with backend.create_threads_portal() as threads_portal:
            with pytest.raises(concurrent.futures.CancelledError):
                await backend.run_in_thread(thread)

    @pytest.mark.parametrize("exception_cls", [Exception, BaseException])
    async def test____create_threads_portal____run_coroutine_from_thread____exception_raised(
        self,
        backend: AsyncBackend,
        exception_cls: type[BaseException],
    ) -> None:
        expected_exception = exception_cls("Why not?")

        async def coroutine(value: int) -> int:
            raise expected_exception

        def thread() -> int:
            return threads_portal.run_coroutine(coroutine, 42)

        threads_portal = backend.create_threads_portal()
        async with threads_portal:
            with pytest.raises(BaseException) as exc_info:
                await backend.run_in_thread(thread)

        assert exc_info.value is expected_exception

    async def test____create_threads_portal____run_coroutine_from_thread____explicit_concurrent_future_Cancelled(
        self,
        backend: AsyncBackend,
    ) -> None:
        async def coroutine(value: int) -> int:
            raise concurrent.futures.CancelledError()

        def thread() -> int:
            with pytest.raises(concurrent.futures.CancelledError):
                return threads_portal.run_coroutine(coroutine, 42)
            return 54

        async with backend.create_threads_portal() as threads_portal:
            assert await backend.run_in_thread(thread) == 54

    async def test____create_threads_portal____run_coroutine_from_thread____sniffio_contextvar_reset(
        self,
        backend: AsyncBackend,
    ) -> None:
        sniffio.current_async_library_cvar.set("main")

        async def coroutine() -> str | None:
            return sniffio.current_async_library_cvar.get()

        def thread() -> str | None:
            return threads_portal.run_coroutine(coroutine)

        async with backend.create_threads_portal() as threads_portal:
            cvar_inner = await backend.run_in_thread(thread)
            cvar_outer = sniffio.current_async_library_cvar.get()

        assert cvar_inner is None
        assert cvar_outer == "main"

    async def test____create_threads_portal____run_sync_from_thread_in_event_loop(
        self,
        backend: AsyncBackend,
    ) -> None:
        import trio

        trio_token = trio.lowlevel.current_trio_token()
        threads_portal = backend.create_threads_portal()

        def not_threadsafe_func(value: int) -> int:
            assert trio.lowlevel.current_trio_token() is trio_token
            return value

        def thread() -> int:
            with pytest.raises(RuntimeError):
                trio.lowlevel.current_trio_token()
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
        backend: AsyncBackend,
    ) -> None:
        import trio

        trio_token = trio.lowlevel.current_trio_token()

        def not_threadsafe_func(value: int) -> int:
            assert trio.lowlevel.current_trio_token() is trio_token
            return value

        def thread() -> int:
            async def main() -> int:
                assert trio.lowlevel.current_trio_token() is not trio_token
                return threads_portal.run_sync(not_threadsafe_func, 42)

            return trio.run(main)

        async with backend.create_threads_portal() as threads_portal:
            assert await backend.run_in_thread(thread) == 42

    @pytest.mark.parametrize("exception_cls", [Exception, BaseException])
    async def test____create_threads_portal____run_sync_from_thread_in_event_loop____exception_raised(
        self,
        backend: AsyncBackend,
        exception_cls: type[BaseException],
    ) -> None:
        expected_exception = exception_cls("Why not?")

        def not_threadsafe_func(value: int) -> int:
            raise expected_exception

        def thread() -> int:
            return threads_portal.run_sync(not_threadsafe_func, 42)

        threads_portal = backend.create_threads_portal()

        async with threads_portal:
            with pytest.raises(BaseException) as exc_info:
                await backend.run_in_thread(thread)

        assert exc_info.value is expected_exception

    async def test____create_threads_portal____run_sync_from_thread_in_event_loop____explicit_concurrent_future_Cancelled(
        self,
        backend: AsyncBackend,
    ) -> None:
        def not_threadsafe_func(value: int) -> int:
            raise concurrent.futures.CancelledError()

        def thread() -> int:
            with pytest.raises(concurrent.futures.CancelledError):
                return threads_portal.run_sync(not_threadsafe_func, 42)
            return 54

        async with backend.create_threads_portal() as threads_portal:
            assert await backend.run_in_thread(thread) == 54

    async def test____create_threads_portal____run_sync_from_thread_in_event_loop____async_function_given(
        self,
        backend: AsyncBackend,
    ) -> None:
        async def coroutine() -> None:
            raise AssertionError("Should not be called")

        def thread() -> None:
            with pytest.raises(TypeError, match=r"^func is a coroutine function.") as exc_info:
                _ = threads_portal.run_sync(coroutine)

            assert exc_info.value.__notes__ == ["You should use run_coroutine() or run_coroutine_soon() instead."]

        async with backend.create_threads_portal() as threads_portal:
            await backend.run_in_thread(thread)

    async def test____create_threads_portal____run_sync_from_thread_in_event_loop____sniffio_contextvar_reset(
        self,
        backend: AsyncBackend,
    ) -> None:
        sniffio.current_async_library_cvar.set("main")

        def callback() -> str | None:
            return sniffio.current_async_library_cvar.get()

        def thread() -> str | None:
            return threads_portal.run_sync(callback)

        async with backend.create_threads_portal() as threads_portal:
            cvar_inner = await backend.run_in_thread(thread)
            cvar_outer = sniffio.current_async_library_cvar.get()

        assert cvar_inner is None
        assert cvar_outer == "main"

    async def test____create_threads_portal____run_sync_soon____future_cancelled_before_call(
        self,
        backend: AsyncBackend,
        mocker: MockerFixture,
    ) -> None:
        import trio

        trio_token = trio.lowlevel.current_trio_token()
        func_stub = mocker.stub()

        def thread() -> None:
            trio_token.run_sync_soon(time.sleep, 1)  # Drastically slow down event loop

            future = threads_portal.run_sync_soon(func_stub, 42)

            with pytest.raises(TimeoutError):
                future.exception(timeout=0.2)

            future.cancel()
            concurrent.futures.wait({future}, timeout=5)  # Test if future.set_running_or_notify_cancel() have been called
            assert future.cancelled()

        async with backend.create_threads_portal() as threads_portal:
            await backend.run_in_thread(thread)

        func_stub.assert_not_called()

    async def test____create_threads_portal____run_coroutine_soon____future_cancelled(
        self,
        backend: AsyncBackend,
    ) -> None:
        def thread() -> None:
            future = threads_portal.run_coroutine_soon(backend.sleep, 1)

            with pytest.raises(TimeoutError):
                future.exception(timeout=0.2)

            future.cancel()
            concurrent.futures.wait({future}, timeout=0.2)  # Test if future.set_running_or_notify_cancel() have been called
            assert future.cancelled()

        async with backend.create_threads_portal() as threads_portal:
            await backend.run_in_thread(thread)

    @pytest.mark.parametrize("value", [42, ValueError("Not caught")], ids=repr)
    async def test____create_threads_portal____run_coroutine_soon____future_cancelled____cancellation_ignored(
        self,
        value: int | Exception,
        backend: AsyncBackend,
        mocker: MockerFixture,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import logging

        import trio

        caplog.set_level(logging.ERROR, "trio")

        cancellation_ignored = mocker.stub()

        subcoroutine_task: list[trio.lowlevel.Task] = []

        async def coroutine() -> int:
            try:
                await trio.sleep(1)
            except trio.Cancelled:
                pass
            await trio.lowlevel.cancel_shielded_checkpoint()
            cancellation_ignored()
            subcoroutine_task.append(trio.lowlevel.current_task())
            if isinstance(value, Exception):
                raise value
            return value

        def thread() -> None:
            future = threads_portal.run_coroutine_soon(coroutine)

            with pytest.raises(TimeoutError):
                future.exception(timeout=0.2)

            future.cancel()
            concurrent.futures.wait({future}, timeout=0.2)  # Test if future.set_running_or_notify_cancel() have been called
            assert future.cancelled()

        async with backend.create_threads_portal() as threads_portal:
            await backend.run_in_thread(thread)

        cancellation_ignored.assert_called_once()
        if isinstance(value, Exception):
            assert len(caplog.records) == 1
            assert caplog.records[0].levelno == logging.ERROR
            assert caplog.records[0].exc_info is not None
            assert caplog.records[0].exc_info[1] is value
            assert caplog.records[0].getMessage() == "\n".join(
                [
                    "Task exception was not retrieved because future object is cancelled",
                    f"task: {subcoroutine_task[0]!r}",
                ]
            )
        else:
            assert len(caplog.records) == 0

    async def test____create_threads_portal____entered_twice(
        self,
        backend: AsyncBackend,
    ) -> None:
        async with backend.create_threads_portal() as threads_portal:
            with pytest.raises(RuntimeError, match=r"ThreadsPortal entered twice\."):
                await threads_portal.__aenter__()
