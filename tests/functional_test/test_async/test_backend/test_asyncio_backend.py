from __future__ import annotations

import asyncio
import contextlib
import time
import warnings
from collections.abc import Awaitable, Callable, Iterator
from concurrent.futures import CancelledError as FutureCancelledError, wait as wait_concurrent_futures
from contextlib import ExitStack
from typing import TYPE_CHECKING, Any, Literal, Required, TypedDict

from easynetwork.lowlevel.api_async.backend.abc import AsyncBackend, TaskInfo
from easynetwork.lowlevel.api_async.backend.utils import new_builtin_backend

import pytest
import sniffio

from ....tools import temporary_exception_handler

if TYPE_CHECKING:
    from unittest.mock import AsyncMock

    from pytest_mock import MockerFixture


class ExceptionCaughtDict(TypedDict, total=False):
    message: Required[str]
    exception: Exception
    future: asyncio.Future[Any]
    task: asyncio.Task[Any]
    handle: asyncio.Handle
    protocol: asyncio.BaseProtocol
    transport: asyncio.BaseTransport


class TestAsyncioBackendBootstrap:
    @pytest.fixture(scope="class")
    @staticmethod
    def backend() -> AsyncBackend:
        return new_builtin_backend("asyncio")

    def test____bootstrap____sniffio_thread_local_reset(
        self,
        backend: AsyncBackend,
    ) -> None:
        assert sniffio.thread_local.name is None

        async def main() -> str | None:
            return sniffio.thread_local.name

        thread_local_inner = backend.bootstrap(main)

        assert thread_local_inner == "asyncio"
        assert sniffio.thread_local.name is None


@pytest.mark.asyncio
@pytest.mark.flaky(retries=3, delay=0.1)
class TestAsyncioBackend:
    @pytest.fixture
    @staticmethod
    def event_loop_exceptions_caught(
        event_loop: asyncio.AbstractEventLoop,
        mocker: MockerFixture,
    ) -> Iterator[list[ExceptionCaughtDict]]:
        event_loop_exceptions_caught: list[ExceptionCaughtDict] = []
        handler_stub = mocker.MagicMock(
            "ExceptionHandler",
            side_effect=lambda loop, context: event_loop_exceptions_caught.append(context),
        )

        with temporary_exception_handler(event_loop, handler_stub):
            yield event_loop_exceptions_caught

    @pytest.fixture(scope="class")
    @staticmethod
    def backend() -> AsyncBackend:
        return new_builtin_backend("asyncio")

    async def test____cancel_shielded_coro_yield____mute_cancellation(
        self,
        backend: AsyncBackend,
    ) -> None:
        task: asyncio.Task[None] = asyncio.create_task(backend.cancel_shielded_coro_yield())

        await asyncio.sleep(0)

        for _ in range(3):
            task.cancel()

        await task
        assert not task.cancelled()

    @pytest.mark.parametrize("cancel_message", ["something", None], ids=lambda p: f"cancel_message=={p!r}")
    async def test____cancel_shielded_coro_yield____cancel_at_the_next_checkpoint(
        self,
        cancel_message: str | None,
        backend: AsyncBackend,
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

        task: asyncio.Task[None] = asyncio.create_task(coroutine())

        await asyncio.sleep(0)

        for _ in range(3):
            task.cancel(msg=cancel_message)

        with pytest.raises(asyncio.CancelledError) as exc_info:
            await task
        assert task.cancelled()
        assert test_list == ["a", "b", "c"]
        if cancel_message is None:
            assert exc_info.value.args == ()
        else:
            assert exc_info.value.args == (cancel_message,)

    async def test____ignore_cancellation____always_continue_on_cancellation(
        self,
        backend: AsyncBackend,
    ) -> None:
        event_loop = asyncio.get_running_loop()
        checkpoints: list[int] = []

        async def coroutine() -> int:
            for i in range(2):
                await asyncio.sleep(0.25)
                checkpoints.append(i)
            return 42

        task: asyncio.Task[int] = asyncio.create_task(backend.ignore_cancellation(coroutine()))

        for i in range(3):
            for _ in range(3):
                event_loop.call_later(0.1 * i, task.cancel)

        assert await task == 42
        assert task.cancelling() > 0
        assert checkpoints == [0, 1]

    @pytest.mark.parametrize("direct_raise", [False, True], ids=lambda p: f"direct_raise=={p}")
    async def test____ignore_cancellation____exception_raised_in_task(
        self,
        direct_raise: bool,
        backend: AsyncBackend,
    ) -> None:
        event_loop = asyncio.get_running_loop()
        exception = Exception("error")

        async def coroutine() -> None:
            if direct_raise:
                raise exception

            f = event_loop.create_future()
            event_loop.call_later(0.5, f.set_exception, exception)
            await f

        task: asyncio.Task[None] = asyncio.create_task(backend.ignore_cancellation(coroutine()))

        for i in range(3):
            for _ in range(3):
                event_loop.call_later(0.1 * i, task.cancel)

        with pytest.raises(Exception) as exc_info:
            await task

        assert task.exception() is exception
        assert exc_info.value is exception

    async def test____ignore_cancellation____runs_in_current_task(
        self,
        backend: AsyncBackend,
    ) -> None:
        async def coroutine() -> asyncio.Task[Any]:
            task = asyncio.current_task()
            assert task is not None
            return task

        assert (await backend.ignore_cancellation(coroutine())) is asyncio.current_task()

    async def test____ignore_cancellation____remove_future_blocking_flag_like_default_implementation(
        self,
        backend: AsyncBackend,
    ) -> None:
        event_loop = asyncio.get_running_loop()

        async def coroutine() -> None:
            f = event_loop.create_future()
            event_loop.call_later(0.5, f.set_result, None)
            await f
            assert f._asyncio_future_blocking is False

        await backend.ignore_cancellation(coroutine())

    async def test____ignore_cancellation____forbid_await_itself_like_default_implementation(
        self,
        backend: AsyncBackend,
    ) -> None:
        async def coroutine() -> None:
            task = asyncio.current_task()
            assert task is not None
            await task

        with pytest.raises(RuntimeError, match=r"^Task cannot await on itself: .+$"):
            await backend.ignore_cancellation(coroutine())

    @pytest.mark.parametrize("with_delay", [False, True], ids=lambda p: f"with_delay=={p}")
    @pytest.mark.parametrize("cancel_method", ["fut_cancel", "raise"], ids=lambda p: f"cancel_method=={p}")
    async def test____ignore_cancellation____coroutine_cancelled_itself(
        self,
        cancel_method: Literal["fut_cancel", "raise"],
        with_delay: bool,
        backend: AsyncBackend,
    ) -> None:
        event_loop = asyncio.get_running_loop()

        def cancel_future(f: asyncio.Future[Any]) -> None:
            match cancel_method:
                case "fut_cancel":
                    f.cancel(msg="message")
                    assert f.cancelled()
                case "raise":
                    f.set_exception(asyncio.CancelledError("message"))
                    assert f.done() and not f.cancelled()

        async def self_cancellation() -> None:
            f = event_loop.create_future()
            if with_delay:
                event_loop.call_later(0.5, cancel_future, f)
            else:
                cancel_future(f)
            await f
            raise AssertionError

        task = asyncio.create_task(backend.ignore_cancellation(self_cancellation()))

        with pytest.raises(asyncio.CancelledError, match=r"^message$"):
            await task
        assert task.cancelled()

    async def test____timeout____respected(
        self,
        backend: AsyncBackend,
    ) -> None:
        with backend.timeout(1):
            assert await asyncio.sleep(0.5, 42) == 42

    async def test____timeout____timeout_error(
        self,
        backend: AsyncBackend,
    ) -> None:
        with pytest.raises(TimeoutError):
            with backend.timeout(0.25):
                await asyncio.sleep(0.5, 42)

    async def test____timeout____cancellation(
        self,
        backend: AsyncBackend,
    ) -> None:
        event_loop = asyncio.get_running_loop()

        async def coroutine() -> None:
            with backend.timeout(0.25):
                await asyncio.sleep(0.5, 42)

        task = asyncio.create_task(coroutine())
        event_loop.call_later(0.10, task.cancel)

        await asyncio.wait({task})
        assert task.cancelled()

    async def test____timeout_at____respected(
        self,
        backend: AsyncBackend,
    ) -> None:
        event_loop = asyncio.get_running_loop()

        with backend.timeout_at(event_loop.time() + 1):
            assert await asyncio.sleep(0.5, 42) == 42

    async def test____timeout_at____timeout_error(
        self,
        backend: AsyncBackend,
    ) -> None:
        event_loop = asyncio.get_running_loop()

        with pytest.raises(TimeoutError):
            with backend.timeout_at(event_loop.time() + 0.25):
                await asyncio.sleep(0.5, 42)

    async def test____timeout_at____cancellation(
        self,
        backend: AsyncBackend,
    ) -> None:
        event_loop = asyncio.get_running_loop()

        async def coroutine() -> None:
            with backend.timeout_at(event_loop.time() + 0.25):
                await asyncio.sleep(0.5, 42)

        task = asyncio.create_task(coroutine())
        event_loop.call_later(0.10, task.cancel)

        await asyncio.wait({task})
        assert task.cancelled()

    async def test____move_on_after____respected(
        self,
        backend: AsyncBackend,
    ) -> None:
        with backend.move_on_after(1) as scope:
            assert await asyncio.sleep(0.5, 42) == 42

        assert not scope.cancelled_caught()

    async def test____move_on_after____timeout_error(
        self,
        backend: AsyncBackend,
    ) -> None:
        with backend.move_on_after(0.25) as scope:
            await asyncio.sleep(0.5, 42)

        assert scope.cancelled_caught()

    async def test____move_on_after____cancellation(
        self,
        backend: AsyncBackend,
    ) -> None:
        event_loop = asyncio.get_running_loop()

        async def coroutine() -> None:
            with backend.move_on_after(0.25):
                await asyncio.sleep(0.5, 42)

        task = asyncio.create_task(coroutine())
        event_loop.call_later(0.10, task.cancel)

        await asyncio.wait({task})
        assert task.cancelled()

    async def test____move_on_at____respected(
        self,
        backend: AsyncBackend,
    ) -> None:
        event_loop = asyncio.get_running_loop()

        with backend.move_on_at(event_loop.time() + 1) as scope:
            assert await asyncio.sleep(0.5, 42) == 42

        assert not scope.cancelled_caught()

    async def test____move_on_at____timeout_error(
        self,
        backend: AsyncBackend,
    ) -> None:
        event_loop = asyncio.get_running_loop()

        with backend.move_on_at(event_loop.time() + 0.25) as scope:
            await asyncio.sleep(0.5, 42)

        assert scope.cancelled_caught()

    async def test____move_on_at____cancellation(
        self,
        backend: AsyncBackend,
    ) -> None:
        event_loop = asyncio.get_running_loop()

        async def coroutine() -> None:
            with backend.move_on_at(event_loop.time() + 0.25):
                await asyncio.sleep(0.5, 42)

        task = asyncio.create_task(coroutine())
        event_loop.call_later(0.10, task.cancel)

        await asyncio.wait({task})
        assert task.cancelled()

    async def test____sleep_forever____sleep_until_cancellation(
        self,
        backend: AsyncBackend,
    ) -> None:
        event_loop = asyncio.get_running_loop()

        sleep_task = asyncio.create_task(backend.sleep_forever())

        event_loop.call_later(0.5, sleep_task.cancel)

        with pytest.raises(asyncio.CancelledError):
            await sleep_task

    async def test____open_cancel_scope____unbound_cancel_scope____cancel_when_entering(
        self,
        backend: AsyncBackend,
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
                scope.cancel()
                await backend.coro_yield()

            assert current_task.cancelling() == 0
            assert scope.cancelled_caught()

        await asyncio.create_task(coroutine())

    async def test____open_cancel_scope____unbound_cancel_scope____deadline_scheduled_when_entering(
        self,
        backend: AsyncBackend,
    ) -> None:
        event_loop = asyncio.get_running_loop()

        async def coroutine() -> None:
            current_task = asyncio.current_task()
            assert current_task is not None

            scope = backend.open_cancel_scope()
            scope.reschedule(event_loop.time() + 1)

            assert current_task.cancelling() == 0
            await asyncio.sleep(0.5)

            with backend.timeout(0.6):
                with scope:
                    await backend.sleep_forever()

            assert scope.cancelled_caught()

        await asyncio.create_task(coroutine())

    async def test____open_cancel_scope____overwrite_defined_deadline(
        self,
        backend: AsyncBackend,
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

        await asyncio.create_task(coroutine())

    async def test____open_cancel_scope____invalid_deadline(
        self,
        backend: AsyncBackend,
    ) -> None:
        with pytest.raises(ValueError):
            _ = backend.open_cancel_scope(deadline=float("nan"))

    async def test____open_cancel_scope____context_reuse(
        self,
        backend: AsyncBackend,
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
        backend: AsyncBackend,
    ) -> None:
        with pytest.raises(RuntimeError, match=r"^This cancel scope is not active$"), ExitStack() as stack:
            stack.push(backend.open_cancel_scope())

    async def test____open_cancel_scope____task_misnesting(
        self,
        backend: AsyncBackend,
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
        backend: AsyncBackend,
    ) -> None:
        stack = ExitStack()
        stack.enter_context(backend.open_cancel_scope())
        with backend.open_cancel_scope():
            with pytest.raises(
                RuntimeError, match=r"^Attempted to exit a cancel scope that isn't the current tasks's current cancel scope$"
            ):
                stack.close()
            stack.pop_all()

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
        async def coroutine(value: int) -> int:
            return await asyncio.sleep(0.5, value)

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
        async def coroutine(value: int) -> int:
            return await backend.ignore_cancellation(asyncio.sleep(0.5, value))

        async def coroutine_error(exception: Exception) -> int:
            await backend.ignore_cancellation(asyncio.sleep(0.5))
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
        awaited = mocker.async_stub()

        async def coroutine(value: int) -> int:
            await awaited()
            return await asyncio.sleep(0.5, value)

        awaitable = coroutine(42)

        result = await backend.gather(awaitable, awaitable, awaitable)

        assert result == [42, 42, 42]
        awaited.assert_awaited_once()

    async def test____create_task_group____start_soon(
        self,
        backend: AsyncBackend,
    ) -> None:
        tasks: list[TaskInfo] = []

        async def coroutine(value: int) -> int:
            tasks.append(backend.get_current_task())
            return await asyncio.sleep(0.5, value)

        async with backend.create_task_group() as tg:
            tg.start_soon(coroutine, 42)
            tg.start_soon(coroutine, 54)
            await asyncio.sleep(0)
            assert len(tasks) == 2

    async def test____create_task_group____start_soon____set_name(
        self,
        backend: AsyncBackend,
    ) -> None:
        tasks: list[TaskInfo] = []

        async def coroutine(value: int) -> int:
            tasks.append(backend.get_current_task())
            return await asyncio.sleep(0.5, value)

        async with backend.create_task_group() as tg:
            tg.start_soon(coroutine, 42, name="compute 42")
            tg.start_soon(coroutine, 54, name="compute 54")
            await asyncio.sleep(0)

        assert sorted(t.name for t in tasks) == ["compute 42", "compute 54"]

    async def test____create_task_group____start_soon____runtime_error(
        self,
        backend: AsyncBackend,
    ) -> None:
        tasks: list[TaskInfo] = []

        async def coroutine(value: int) -> int:
            tasks.append(backend.get_current_task())
            return await asyncio.sleep(0.5, value)

        async with backend.create_task_group() as tg:
            await asyncio.sleep(0)

        with warnings.catch_warnings(record=True, action="always", category=RuntimeWarning) as retrieved_warnings:
            with pytest.raises(RuntimeError):
                tg.start_soon(coroutine, 42)
            assert len(tasks) == 0
            assert not retrieved_warnings, list(map(str, retrieved_warnings))

    async def test____create_task_group____start_and_wait(
        self,
        backend: AsyncBackend,
    ) -> None:
        tasks: list[TaskInfo] = []

        async def coroutine(value: int) -> int:
            tasks.append(backend.get_current_task())
            return await asyncio.sleep(0.5, value)

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
        assert await task_42.join() == 42
        assert await task_54.join() == 54

    async def test____create_task_group____start_and_wait____set_name(
        self,
        backend: AsyncBackend,
    ) -> None:
        async def coroutine(value: int) -> int:
            return await asyncio.sleep(0.5, value)

        async with backend.create_task_group() as tg:
            task_42 = await tg.start(coroutine, 42, name="compute 42")
            task_54 = await tg.start(coroutine, 54, name="compute 54")

            assert task_42.info.name == "compute 42"
            assert task_54.info.name == "compute 54"

    async def test____create_task_group____start_and_wait____waiter_cancelled(
        self,
        backend: AsyncBackend,
        mocker: MockerFixture,
    ) -> None:
        awaited = mocker.async_stub()

        async def coroutine(value: int) -> int:
            await awaited()
            return await asyncio.sleep(0.5, value)

        async with backend.create_task_group() as tg:
            with backend.move_on_after(0):
                await tg.start(coroutine, 42, name="compute 42")

        awaited.assert_not_awaited()

    async def test____create_task_group____start_and_wait____runtime_error(
        self,
        backend: AsyncBackend,
    ) -> None:
        tasks: list[TaskInfo] = []

        async def coroutine(value: int) -> int:
            tasks.append(backend.get_current_task())
            return await asyncio.sleep(0.5, value)

        async with backend.create_task_group() as tg:
            await asyncio.sleep(0)

        with warnings.catch_warnings(record=True, action="always", category=RuntimeWarning) as retrieved_warnings:
            with pytest.raises(RuntimeError):
                await tg.start(coroutine, 42)
            assert len(tasks) == 0
            assert not retrieved_warnings, list(map(str, retrieved_warnings))

    async def test____create_task_group____task_cancellation(
        self,
        backend: AsyncBackend,
    ) -> None:
        async def coroutine(value: int) -> int:
            return await asyncio.sleep(0.5, value)

        async with backend.create_task_group() as tg:
            task_42 = await tg.start(coroutine, 42)
            task_54 = await tg.start(coroutine, 54)

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

    @pytest.mark.parametrize("join_method", ["join", "join_or_cancel", "wait"])
    async def test____create_task_group____task_join_cancel_shielding(
        self,
        join_method: Literal["join", "join_or_cancel", "wait"],
        backend: AsyncBackend,
    ) -> None:
        event_loop = asyncio.get_running_loop()

        async def coroutine(value: int) -> int:
            return await asyncio.sleep(0.5, value)

        async with backend.create_task_group() as task_group:
            inner_task = await task_group.start(coroutine, 42)

            outer_task: asyncio.Task[Any]
            match join_method:
                case "join":
                    outer_task = asyncio.create_task(inner_task.join())
                case "join_or_cancel":
                    outer_task = asyncio.create_task(inner_task.join_or_cancel())
                case "wait":
                    outer_task = asyncio.create_task(inner_task.wait())
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

    @pytest.mark.parametrize("task_state", ["result", "exception", "cancelled"])
    async def test____create_task_group____task_wait(
        self,
        task_state: Literal["result", "exception", "cancelled"],
        backend: AsyncBackend,
    ) -> None:
        event_loop = asyncio.get_running_loop()
        future: asyncio.Future[None] = event_loop.create_future()

        class FutureException(Exception):
            pass

        def set_future_result() -> None:
            match task_state:
                case "result":
                    future.set_result(None)
                case "exception":
                    future.set_exception(FutureException("Error"))
                case "cancelled":
                    future.cancel()
                case _:
                    pytest.fail("invalid argument")

        async def coroutine() -> None:
            return await future

        event_loop.call_later(0.1, set_future_result)

        with pytest.raises(ExceptionGroup) if task_state == "exception" else contextlib.nullcontext() as exc_info:
            async with backend.create_task_group() as task_group:
                task = await task_group.start(coroutine)

                await task.wait()
                assert task.done()

                # Must not yield if task is already done
                async with asyncio.timeout(0):
                    await task.wait()

        if exc_info is not None:
            assert exc_info.group_contains(FutureException, depth=1)

    async def test____create_task_group____do_not_wrap_exception_from_within_context(
        self,
        backend: AsyncBackend,
    ) -> None:
        async def coroutine(value: int) -> int:
            return await backend.ignore_cancellation(asyncio.sleep(0.5, value))

        with pytest.raises(ValueError, match=r"^unwrapped exception$"):
            async with backend.create_task_group() as task_group:
                task_group.start_soon(coroutine, 42)
                task_group.start_soon(coroutine, 54)
                await backend.coro_yield()
                raise ValueError("unwrapped exception")

    async def test____run_in_thread____cannot_be_cancelled_by_default(
        self,
        backend: AsyncBackend,
    ) -> None:
        event_loop = asyncio.get_running_loop()
        task = asyncio.create_task(backend.run_in_thread(time.sleep, 0.5))
        event_loop.call_later(0.1, task.cancel)
        event_loop.call_later(0.2, task.cancel)
        event_loop.call_later(0.3, task.cancel)
        event_loop.call_later(0.4, task.cancel)

        await task

        assert not task.cancelled()

    async def test____run_in_thread____abandon_on_cancel(
        self,
        backend: AsyncBackend,
    ) -> None:
        event_loop = asyncio.get_running_loop()
        task = asyncio.create_task(backend.run_in_thread(time.sleep, 0.5, abandon_on_cancel=True))
        event_loop.call_later(0.1, task.cancel)

        with pytest.raises(asyncio.CancelledError):
            await task

        assert task.cancelled()

    async def test____run_in_thread____sniffio_contextvar_reset(self, backend: AsyncBackend) -> None:
        sniffio.current_async_library_cvar.set("asyncio")

        def callback() -> str | None:
            return sniffio.current_async_library_cvar.get()

        cvar_inner = await backend.run_in_thread(callback)
        cvar_outer = sniffio.current_async_library_cvar.get()

        assert cvar_inner is None
        assert cvar_outer == "asyncio"

    async def test____create_threads_portal____run_coroutine_from_thread(
        self,
        backend: AsyncBackend,
    ) -> None:
        event_loop = asyncio.get_running_loop()
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
        backend: AsyncBackend,
    ) -> None:
        event_loop = asyncio.get_running_loop()

        async def coroutine(value: int) -> int:
            assert asyncio.get_running_loop() is event_loop
            return await asyncio.sleep(0.5, value)

        def thread() -> int:
            async def main() -> int:
                assert asyncio.get_running_loop() is not event_loop
                return threads_portal.run_coroutine(coroutine, 42)

            return asyncio.run(main())

        async with backend.create_threads_portal() as threads_portal:
            assert await backend.run_in_thread(thread) == 42

    @pytest.mark.parametrize("exception_cls", [Exception, BaseException])
    async def test____create_threads_portal____run_coroutine_from_thread____exception_raised(
        self,
        backend: AsyncBackend,
        exception_cls: type[BaseException],
        event_loop_exceptions_caught: list[ExceptionCaughtDict],
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
        assert len(event_loop_exceptions_caught) == 0

    async def test____create_threads_portal____run_coroutine_from_thread____coroutine_cancelled(
        self,
        backend: AsyncBackend,
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
        backend: AsyncBackend,
    ) -> None:
        async def coroutine(value: int) -> int:
            raise FutureCancelledError()

        def thread() -> int:
            with pytest.raises(FutureCancelledError):
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

        assert cvar_inner == "asyncio"
        assert cvar_outer == "main"

    async def test____create_threads_portal____run_sync_from_thread_in_event_loop(
        self,
        backend: AsyncBackend,
    ) -> None:
        event_loop = asyncio.get_running_loop()
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
        backend: AsyncBackend,
    ) -> None:
        event_loop = asyncio.get_running_loop()

        def not_threadsafe_func(value: int) -> int:
            assert asyncio.get_running_loop() is event_loop
            return value

        def thread() -> int:
            async def main() -> int:
                assert asyncio.get_running_loop() is not event_loop
                return threads_portal.run_sync(not_threadsafe_func, 42)

            return asyncio.run(main())

        async with backend.create_threads_portal() as threads_portal:
            assert await backend.run_in_thread(thread) == 42

    @pytest.mark.parametrize("exception_cls", [Exception, BaseException])
    async def test____create_threads_portal____run_sync_from_thread_in_event_loop____exception_raised(
        self,
        backend: AsyncBackend,
        exception_cls: type[BaseException],
        event_loop_exceptions_caught: list[ExceptionCaughtDict],
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
        assert len(event_loop_exceptions_caught) == 0

    async def test____create_threads_portal____run_sync_from_thread_in_event_loop____explicit_concurrent_future_Cancelled(
        self,
        backend: AsyncBackend,
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

        assert cvar_inner == "asyncio"
        assert cvar_outer == "main"

    async def test____create_threads_portal____run_sync_soon____future_cancelled_before_call(
        self,
        backend: AsyncBackend,
        mocker: MockerFixture,
    ) -> None:
        event_loop = asyncio.get_running_loop()
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
        backend: AsyncBackend,
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
        backend: AsyncBackend,
        event_loop_exceptions_caught: list[ExceptionCaughtDict],
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
        if isinstance(value, Exception):
            assert len(event_loop_exceptions_caught) == 1
            assert (
                event_loop_exceptions_caught[0]["message"]
                == "Task exception was not retrieved because future object is cancelled"
            )
            assert event_loop_exceptions_caught[0]["exception"] is value
            assert isinstance(event_loop_exceptions_caught[0]["task"], asyncio.Task)
        else:
            assert len(event_loop_exceptions_caught) == 0

    async def test____create_threads_portal____run_coroutine_soon____future_cancelled_before_await(
        self,
        backend: AsyncBackend,
    ) -> None:
        event_loop = asyncio.get_running_loop()
        checkpoints: list[str] = []

        async def coroutine() -> None:
            current_task = asyncio.current_task()
            assert current_task is not None

            checkpoints.append("task started")
            await asyncio.sleep(0)
            checkpoints.append("does-not-raise-CancelledError")

        def thread() -> None:
            future = threads_portal.run_coroutine_soon(coroutine)
            future.cancel()

            wait_concurrent_futures({future}, timeout=5)  # Test if future.set_running_or_notify_cancel() have been called
            assert future.cancelled()

        event_loop_slowdown_handle: asyncio.Handle

        def event_loop_slowdown() -> None:  # Drastically slow down event loop
            nonlocal event_loop_slowdown_handle

            time.sleep(0.5)
            event_loop_slowdown_handle = event_loop.call_soon(event_loop_slowdown)

        event_loop_slowdown_handle = event_loop.call_soon(event_loop_slowdown)
        async with backend.create_threads_portal() as threads_portal:
            await backend.run_in_thread(thread)

        event_loop_slowdown_handle.cancel()
        assert checkpoints == ["task started"]

    @pytest.mark.skipif(not hasattr(asyncio, "eager_task_factory"), reason="asyncio.eager_task_factory not implemented")
    async def test____create_threads_portal____run_coroutine_soon____eager_task(
        self,
        backend: AsyncBackend,
    ) -> None:
        event_loop = asyncio.get_running_loop()
        event_loop.set_task_factory(getattr(asyncio, "eager_task_factory"))

        async def coroutine() -> int:
            return 42

        def thread() -> None:
            future = threads_portal.run_coroutine_soon(coroutine)
            assert future.result() == 42

        async with backend.create_threads_portal() as threads_portal:
            await backend.run_in_thread(thread)

    async def test____create_threads_portal____context_exit____wait_scheduled_call_soon(
        self,
        backend: AsyncBackend,
        mocker: MockerFixture,
    ) -> None:
        event_loop = asyncio.get_running_loop()
        func_stub = mocker.stub()
        func_stub.return_value = "Hello, world!"

        def thread() -> None:
            future = threads_portal.run_sync_soon(func_stub, 42)
            assert future.result(timeout=1) == "Hello, world!"

        async with backend.create_threads_portal() as threads_portal:
            task = asyncio.create_task(backend.run_in_thread(thread))
            event_loop.call_soon(time.sleep, 0.5)
            await asyncio.sleep(0)

        func_stub.assert_called_once_with(42)
        await task

    async def test____create_threads_portal____context_exit____wait_scheduled_call_soon_for_coroutine(
        self,
        backend: AsyncBackend,
        mocker: MockerFixture,
    ) -> None:
        event_loop = asyncio.get_running_loop()
        coro_stub: AsyncMock = mocker.async_stub()
        coro_stub.return_value = "Hello, world!"

        def thread() -> None:
            future = threads_portal.run_coroutine_soon(coro_stub, 42)
            assert future.result(timeout=1) == "Hello, world!"

        async with backend.create_threads_portal() as threads_portal:
            task = asyncio.create_task(backend.run_in_thread(thread))
            event_loop.call_soon(time.sleep, 0.5)
            await asyncio.sleep(0)

        coro_stub.assert_awaited_once_with(42)
        await task

    async def test____create_threads_portal____entered_twice(
        self,
        backend: AsyncBackend,
    ) -> None:
        async with backend.create_threads_portal() as threads_portal:
            with pytest.raises(RuntimeError, match=r"ThreadsPortal entered twice\."):
                await threads_portal.__aenter__()


@pytest.mark.asyncio
@pytest.mark.flaky(retries=3, delay=0.1)
class TestAsyncioBackendShieldedCancellation:
    @pytest.fixture(scope="class")
    @staticmethod
    def backend() -> AsyncBackend:
        return new_builtin_backend("asyncio")

    @pytest.fixture(
        params=[
            "cancel_shielded_coro_yield",
            "ignore_cancellation",
            "ignore_cancellation(coro_yield)",
            "run_in_thread",
            "cancel_shielded_wait_asyncio_futures",
        ]
    )
    @staticmethod
    def cancel_shielded_coroutine(
        request: pytest.FixtureRequest,
        backend: AsyncBackend,
    ) -> Callable[[], Awaitable[Any]]:
        match getattr(request, "param"):
            case "cancel_shielded_coro_yield":
                return backend.cancel_shielded_coro_yield
            case "ignore_cancellation":
                return lambda: backend.ignore_cancellation(backend.sleep(0.1))
            case "ignore_cancellation(coro_yield)":
                return lambda: backend.ignore_cancellation(backend.coro_yield())
            case "run_in_thread":
                return lambda: backend.run_in_thread(time.sleep, 0.1)
            case "cancel_shielded_wait_asyncio_futures":
                from easynetwork.lowlevel.api_async.backend._asyncio.tasks import TaskUtils

                async def cancel_shielded_wait_asyncio_futures() -> None:
                    loop = asyncio.get_running_loop()
                    futures = [loop.create_future() for _ in range(3)]
                    for i, f in enumerate(futures, start=1):
                        loop.call_later(0.1 * i, f.set_result, None)
                    await TaskUtils.cancel_shielded_await(asyncio.wait(futures))

                return cancel_shielded_wait_asyncio_futures
            case _:
                pytest.fail("Invalid parameter")

    async def test____cancel_shielded_coroutine____do_not_cancel_at_timeout_end(
        self,
        cancel_shielded_coroutine: Callable[[], Awaitable[Any]],
        backend: AsyncBackend,
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

        task = asyncio.create_task(coroutine(42))

        assert await task == 42
        assert checkpoints == ["cancel_shielded_coroutine", "coro_yield"]

    async def test____cancel_shielded_coroutine____cancel_at_timeout_end_if_nested(
        self,
        cancel_shielded_coroutine: Callable[[], Awaitable[Any]],
        backend: AsyncBackend,
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

                    await cancel_shielded_coroutine()
                    checkpoints.append("cancel_shielded_coroutine")

                checkpoints.append("inner_coro_yield")
                await backend.coro_yield()
                checkpoints.append("should_not_be_here")

            assert scope.cancel_called()
            assert scope.cancelled_caught()
            await backend.coro_yield()
            checkpoints.append("coro_yield")
            return value

        task = asyncio.create_task(coroutine(42))

        assert await task == 42
        assert checkpoints == ["inner_cancel_shielded_coroutine", "cancel_shielded_coroutine", "inner_coro_yield", "coro_yield"]

    async def test____timeout____cancel_at_timeout_end_if_task_cancellation_were_already_delayed(
        self,
        cancel_shielded_coroutine: Callable[[], Awaitable[Any]],
        backend: AsyncBackend,
    ) -> None:
        event_loop = asyncio.get_running_loop()
        checkpoints: list[str] = []

        async def coroutine(value: int) -> int:
            current_task = asyncio.current_task()
            assert current_task is not None

            await cancel_shielded_coroutine()
            checkpoints.append("cancel_shielded_coroutine")

            with backend.timeout(0), backend.open_cancel_scope():
                await cancel_shielded_coroutine()
                checkpoints.append("inner_cancel_shielded_coroutine")

            await backend.coro_yield()
            checkpoints.append("should_not_be_here")
            return value

        task = asyncio.create_task(coroutine(42))
        event_loop.call_soon(task.cancel)

        with pytest.raises(asyncio.CancelledError):
            await task
        assert checkpoints == ["cancel_shielded_coroutine", "inner_cancel_shielded_coroutine"]

    async def test____cancel_shielded_coroutine____cancel_at_timeout_end_if_task_cancellation_does_not_come_from_scope(
        self,
        cancel_shielded_coroutine: Callable[[], Awaitable[Any]],
        backend: AsyncBackend,
    ) -> None:
        event_loop = asyncio.get_running_loop()
        checkpoints: list[str] = []

        async def coroutine(value: int) -> int:
            current_task = asyncio.current_task()
            assert current_task is not None

            with backend.open_cancel_scope():
                with backend.open_cancel_scope():
                    await cancel_shielded_coroutine()
                    checkpoints.append("cancel_shielded_coroutine")

            await backend.coro_yield()
            checkpoints.append("should_not_be_here")
            return value

        task = asyncio.create_task(coroutine(42))
        event_loop.call_soon(task.cancel)

        with pytest.raises(asyncio.CancelledError):
            await task
        assert checkpoints == ["cancel_shielded_coroutine"]

    async def test____cancel_shielded_coroutine____scope_cancellation_edge_case_1(
        self,
        backend: AsyncBackend,
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

            assert outer_scope.cancelled_caught()
            assert not inner_scope.cancelled_caught()

        await asyncio.create_task(coroutine())

    async def test____cancel_shielded_coroutine____scope_cancellation_edge_case_2(
        self,
        backend: AsyncBackend,
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
                await backend.coro_yield()
                await backend.sleep(1)

            assert outer_scope.cancel_called()
            assert inner_scope.cancel_called()

            assert outer_scope.cancelled_caught()
            assert not inner_scope.cancelled_caught()

        await asyncio.create_task(coroutine())

    async def test____cancel_shielded_coroutine____scope_cancellation_edge_case_3(
        self,
        backend: AsyncBackend,
    ) -> None:
        async def coroutine() -> None:
            current_task = asyncio.current_task()
            assert current_task is not None

            with backend.move_on_after(0) as inner_scope:
                pass

            await backend.coro_yield()

            assert inner_scope.cancel_called()

            assert not inner_scope.cancelled_caught()

        await asyncio.create_task(coroutine())

    async def test____cancel_shielded_coroutine____scope_cancellation_edge_case_4(
        self,
        backend: AsyncBackend,
    ) -> None:
        async def coroutine() -> None:
            current_task = asyncio.current_task()
            assert current_task is not None

            with backend.open_cancel_scope() as inner_scope:
                inner_scope.cancel()

            await backend.coro_yield()

            assert inner_scope.cancel_called()

            assert not inner_scope.cancelled_caught()

        await asyncio.create_task(coroutine())

    async def test____cancel_shielded_coroutine____scope_cancellation_edge_case_5(
        self,
        backend: AsyncBackend,
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

        await asyncio.create_task(coroutine())

    async def test____cancel_shielded_coroutine____scope_cancellation_edge_case_6(
        self,
        backend: AsyncBackend,
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

        await asyncio.create_task(coroutine())

    async def test____ignore_cancellation____do_not_reschedule_if_inner_task_raises_CancelledError(
        self,
        backend: AsyncBackend,
    ) -> None:
        event_loop = asyncio.get_running_loop()

        async def self_cancellation() -> None:
            f = event_loop.create_future()
            event_loop.call_later(0.5, f.cancel)
            await f

        checkpoints: list[str] = []

        async def coroutine() -> None:
            try:
                await backend.ignore_cancellation(self_cancellation())
            except asyncio.CancelledError:
                await asyncio.sleep(0)
                checkpoints.append("inner_yield_in_cancel")
                raise

        task = asyncio.create_task(coroutine())
        event_loop.call_soon(task.cancel)

        with pytest.raises(asyncio.CancelledError):
            await task

        assert checkpoints == ["inner_yield_in_cancel"]

    async def test____ignore_cancellation____reschedule_erased_cancel_from_parent(
        self,
        backend: AsyncBackend,
    ) -> None:
        checkpoints: list[str] = []

        async def coroutine() -> None:
            with backend.open_cancel_scope() as parent_scope:
                parent_scope.cancel()

                try:
                    await backend.sleep_forever()
                except asyncio.CancelledError:
                    pass

                checkpoints.append("cancel_erased")

                await backend.ignore_cancellation(backend.sleep(0.1))
                checkpoints.append("ignore_cancellation_called")

                await backend.coro_yield()
                checkpoints.append("should_not_be_here")

            checkpoints.append("parent_scope_cancelled_caught")

        await asyncio.create_task(coroutine())

        assert checkpoints == ["cancel_erased", "ignore_cancellation_called", "parent_scope_cancelled_caught"]

    async def test____cancel_scope____catch_and_reraise_cancellation(
        self,
        backend: AsyncBackend,
    ) -> None:
        # A function which could do that: asyncio.Condition.wait()

        async def coroutine() -> None:
            current_task = asyncio.current_task()
            assert current_task is not None

            with backend.open_cancel_scope() as outer_scope:
                outer_scope.cancel()
                try:
                    await backend.sleep_forever()
                finally:
                    raise asyncio.CancelledError

            assert outer_scope.cancelled_caught()
            assert not current_task.cancelling()

        await asyncio.create_task(coroutine())

    async def test____cancel_scope____catch_and_reraise_cancellation____skip_unrelated_exceptions(
        self,
        backend: AsyncBackend,
    ) -> None:
        async def coroutine() -> None:
            current_task = asyncio.current_task()
            assert current_task is not None

            with pytest.raises(TimeoutError, match=r"while cancelling") as exc_info:
                with backend.open_cancel_scope() as outer_scope:
                    outer_scope.cancel()
                    try:
                        await backend.sleep_forever()
                    finally:
                        raise TimeoutError("while cancelling")

            assert isinstance(exc_info.value.__context__, asyncio.CancelledError)
            assert not outer_scope.cancelled_caught()
            assert not current_task.cancelling()

        await asyncio.create_task(coroutine())

    async def test____cancel_scope____catch_and_reraise_cancellation___within_exception_group(
        self,
        backend: AsyncBackend,
    ) -> None:
        async def coroutine() -> None:
            current_task = asyncio.current_task()
            assert current_task is not None

            with backend.open_cancel_scope() as outer_scope:
                outer_scope.cancel()
                exceptions: list[BaseException] = []
                try:
                    await backend.sleep_forever()
                except asyncio.CancelledError as exc:
                    exceptions.append(exc)

                raise BaseExceptionGroup("group to swallow", exceptions)

            assert outer_scope.cancelled_caught()
            assert not current_task.cancelling()

        await asyncio.create_task(coroutine())

    async def test____cancel_scope____catch_and_reraise_cancellation___within_exception_group___not_alone(
        self,
        backend: AsyncBackend,
    ) -> None:
        async def coroutine() -> None:
            current_task = asyncio.current_task()
            assert current_task is not None

            with pytest.raises(BaseExceptionGroup) as exc_info:
                with backend.open_cancel_scope() as outer_scope:
                    outer_scope.cancel()
                    exceptions: list[BaseException] = [KeyError("key")]
                    try:
                        await backend.sleep_forever()
                    except asyncio.CancelledError as exc:
                        exceptions.append(exc)

                    raise BaseExceptionGroup("group to skip", exceptions)

            assert exc_info.group_contains(KeyError, match=r"key")
            assert exc_info.group_contains(asyncio.CancelledError, match=r"Cancelled by cancel scope .+")
            assert outer_scope.cancelled_caught(), "outer_scope should consider cancellation as caught even if not suppressed."
            assert not current_task.cancelling()

        await asyncio.create_task(coroutine())

    async def test____cancel_scope____cancelled_scope_based_checkpoint(
        self,
        backend: AsyncBackend,
    ) -> None:
        # Origin: https://github.com/agronholm/anyio/pull/774#discussion_r1766604109

        checkpoints: list[str] = []

        async def coroutine() -> None:
            current_task = asyncio.current_task()
            assert current_task is not None

            with backend.open_cancel_scope() as outer_scope:
                outer_scope.cancel()

                checkpoints.append("outer_scope_cancel")

                try:
                    # The following three lines are a way to implement a checkpoint
                    # function. See also https://github.com/python-trio/trio/issues/860.
                    with backend.open_cancel_scope() as inner_scope:
                        inner_scope.cancel()
                        checkpoints.append("inner_scope_cancel")
                        await backend.sleep_forever()
                finally:
                    assert current_task.cancelling()
                    checkpoints.append("current_task_cancelling_in_outer_scope")

                pytest.fail("checkpoint should have raised")

            assert not current_task.cancelling()
            checkpoints.append("current_task_uncancelled")

        await asyncio.create_task(coroutine())
        assert checkpoints == [
            "outer_scope_cancel",
            "inner_scope_cancel",
            "current_task_cancelling_in_outer_scope",
            "current_task_uncancelled",
        ]
