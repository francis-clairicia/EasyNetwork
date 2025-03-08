# Copyright 2021-2025, Francis Clairicia-Rose-Claire-Josephine
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
#
"""Asynchronous backend engine interfaces module."""

from __future__ import annotations

__all__ = [
    "AsyncBackend",
    "CancelScope",
    "ICondition",
    "IEvent",
    "ILock",
    "Task",
    "TaskGroup",
    "TaskInfo",
    "ThreadsPortal",
]

import concurrent.futures
import dataclasses
import math
import socket as _socket
from abc import ABCMeta, abstractmethod
from collections.abc import Awaitable, Callable, Coroutine, Mapping, Sequence
from contextlib import AbstractContextManager
from types import TracebackType
from typing import Any, Generic, Literal, NoReturn, ParamSpec, Protocol, Self, TypeVar, TypeVarTuple, Unpack

from ..transports import abc as _transports

_P = ParamSpec("_P")
_T = TypeVar("_T")
_T_co = TypeVar("_T_co", covariant=True)
_T_PosArgs = TypeVarTuple("_T_PosArgs")


class ILock(Protocol):
    """
    A mutex lock for asynchronous tasks. Not thread-safe.

    A lock can be used to guarantee exclusive access to a shared resource.

    The preferred way to use a Lock is an :keyword:`async with` statement::

        lock = backend.create_lock()

        # ... later
        async with lock:
            # access shared state

    which is equivalent to::

        lock = backend.create_lock()

        # ... later
        await lock.acquire()
        try:
            # access shared state
        finally:
            lock.release()
    """

    @abstractmethod
    async def __aenter__(self) -> Any: ...

    @abstractmethod
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
        /,
    ) -> Literal[False] | None: ...

    @abstractmethod
    async def acquire(self) -> Any:
        """
        Acquires the lock.

        This method waits until the lock is *unlocked*, sets it to *locked*.

        When more than one coroutine is blocked in :meth:`acquire` waiting for the lock to be unlocked,
        only one coroutine eventually proceeds.
        """
        ...

    @abstractmethod
    def release(self) -> None:
        """
        Releases the lock.

        When the lock is locked, reset it to unlocked and return.

        Raises:
            RuntimeError: the lock is *unlocked* or the task does not have the lock ownership.
        """
        ...

    @abstractmethod
    def locked(self) -> bool:
        """
        Returns True if the lock is locked.

        Returns:
            the lock state.
        """
        ...


class IEvent(Protocol):
    """
    A waitable boolean value useful for inter-task synchronization. Not thread-safe.

    An event object has an internal boolean flag, representing whether the event has happened yet.
    The flag is initially :data:`False`, and the :meth:`wait` method waits until the flag is :data:`True`.
    If the flag is already :data:`True`, then :meth:`wait` returns immediately. (If the event has already happened,
    there's nothing to wait for.) The :meth:`set` method sets the flag to :data:`True`, and wakes up any waiters.

    This behavior is useful because it helps avoid race conditions and lost wakeups: it doesn't matter whether :meth:`set`
    gets called just before or after :meth:`wait`.
    """

    @abstractmethod
    async def wait(self) -> Any:
        """
        Blocks until the internal flag value becomes :data:`True`.

        If it is already :data:`True`, then this method returns immediately.
        """
        ...

    @abstractmethod
    def set(self) -> None:
        """
        Sets the internal flag value to :data:`True`, and wake any waiting tasks.
        """
        ...

    @abstractmethod
    def is_set(self) -> bool:
        """
        Returns:
            the current value of the internal flag.
        """
        ...


class ICondition(ILock, Protocol):
    """
    A classic condition variable, similar to :class:`threading.Condition`.

    """

    @abstractmethod
    def notify(self, n: int = ..., /) -> None:
        """
        Wake one or more tasks that are blocked in :meth:`wait`.
        """
        ...

    @abstractmethod
    def notify_all(self) -> None:
        """
        Wake all tasks that are blocked in :meth:`wait`.
        """
        ...

    @abstractmethod
    async def wait(self) -> Any:
        """
        Wait until notified.

        Raises:
            RuntimeError: The underlying lock is not held by this task.
        """
        ...


class Task(Generic[_T_co], metaclass=ABCMeta):
    """
    A :class:`Task` object represents a concurrent "thread" of execution.
    """

    __slots__ = ("__weakref__",)

    @property
    @abstractmethod
    def info(self) -> TaskInfo:
        """The task data. Read-only attribute."""
        raise NotImplementedError

    @abstractmethod
    def done(self) -> bool:
        """
        Returns the Task state.

        A Task is *done* when the wrapped coroutine either returned a value, raised an exception, or the Task was cancelled.

        Returns:
            :data:`True` if the Task is done.
        """
        raise NotImplementedError

    @abstractmethod
    def cancel(self) -> bool:
        """
        Request the Task to be cancelled.

        This arranges for a ``backend.get_cancelled_exc_class()`` exception to be thrown into the wrapped coroutine
        on the next cycle of the event loop.

        :meth:`Task.cancel` does not guarantee that the Task will be cancelled,
        although suppressing cancellation completely is not common and is actively discouraged.

        Returns:
            :data:`True` if the cancellation request have been taken into account.
            :data:`False` if the task is already *done*.
        """
        raise NotImplementedError

    @abstractmethod
    def cancelled(self) -> bool:
        """
        Returns the cancellation state.

        The Task is *cancelled* when the cancellation was requested with :meth:`cancel` and the wrapped coroutine propagated
        the ``backend.get_cancelled_exc_class()`` exception thrown into it.

        Returns:
            :data:`True` if the Task is *cancelled*
        """
        raise NotImplementedError

    @abstractmethod
    async def wait(self) -> None:
        """
        Blocks until the task has been completed, but *does not* unwrap the result.

        See the :meth:`join` method to get the actual task state.

        Important:
            Cancelling :meth:`Task.wait` *does not* cancel the task.
        """
        raise NotImplementedError

    @abstractmethod
    async def join(self) -> _T_co:
        """
        Blocks until the task has been completed, and returns the result.

        Important:
            Cancelling :meth:`Task.join` *does not* cancel the task.

        Raises:
            backend.get_cancelled_exc_class(): The task was cancelled.
            BaseException: Any exception raised by the task.

        Returns:
            the task result.
        """
        raise NotImplementedError

    @abstractmethod
    async def join_or_cancel(self) -> _T_co:
        """
        Similar to :meth:`Task.join` except that if the coroutine is cancelled, the cancellation is propagated to this task.

        Roughly equivalent to::

            try:
                await task.wait()
            except backend.get_cancelled_exc_class():
                task.cancel()
                await backend.ignore_cancellation(task.wait())
                if task.cancelled():
                    raise
            assert task.done()
            return await task.join()
        """
        raise NotImplementedError


@dataclasses.dataclass(eq=False, slots=True, frozen=True)
class TaskInfo:
    """
    Represents an asynchronous task.
    """

    id: int
    "The unique identifier of the task"
    name: str
    "The description of the task (if any)"
    coro: Coroutine[Any, Any, Any] | None = dataclasses.field(repr=False)
    "The coroutine object of the task"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, TaskInfo):
            return self.id == other.id
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.id)


class CancelScope(metaclass=ABCMeta):
    """
    A temporary scope opened by a task that can be used by other tasks to control its execution time.

    Warning:
        Unlike trio's ``CancelScope``, there is no "shielded" scopes; you must use :meth:`AsyncBackend.ignore_cancellation`.
    """

    __slots__ = ("__weakref__",)

    @abstractmethod
    def __enter__(self) -> Self:
        raise NotImplementedError

    @abstractmethod
    def __exit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None) -> bool:
        raise NotImplementedError

    @abstractmethod
    def cancel(self) -> None:
        """
        Request the Task to be cancelled.

        This arranges for a ``backend.get_cancelled_exc_class()`` exception to be thrown into the wrapped coroutine
        on the next cycle of the event loop.

        :meth:`CancelScope.cancel` does not guarantee that the Task will be cancelled,
        although suppressing cancellation completely is not common and is actively discouraged.
        """
        raise NotImplementedError

    @abstractmethod
    def cancel_called(self) -> bool:
        """
        Checks if :meth:`cancel` has been called.

        Returns:
            :data:`True` if :meth:`cancel` has been called.
        """
        raise NotImplementedError

    @abstractmethod
    def cancelled_caught(self) -> bool:
        """
        Returns the scope cancellation state.

        Returns:
            :data:`True` if the scope has been *cancelled*.
        """
        raise NotImplementedError

    @abstractmethod
    def when(self) -> float:
        """
        Returns the current deadline.

        Returns:
            the absolute time in seconds. :data:`math.inf` if the current deadline is not set.
        """
        raise NotImplementedError

    @abstractmethod
    def reschedule(self, when: float, /) -> None:
        """
        Reschedules the timeout.

        Parameters:
            when: The new deadline.
        """
        raise NotImplementedError

    @property
    def deadline(self) -> float:
        """
        A read-write attribute to simplify the timeout management.

        For example, this statement::

            scope.deadline += 30

        is equivalent to::

            scope.reschedule(scope.when() + 30)

        It is also possible to remove the timeout by "deleting" the attribute::

            del scope.deadline
        """
        return self.when()

    @deadline.setter
    def deadline(self, value: float) -> None:
        self.reschedule(value)

    @deadline.deleter
    def deadline(self) -> None:
        self.reschedule(math.inf)


class TaskGroup(metaclass=ABCMeta):
    """
    Groups several asynchronous tasks together.

    Example::

        async def main():
            async with backend.create_task_group() as tg:
                tg.start_soon(some_coro)
                tg.start_soon(another_coro)
            print("Both tasks have completed now.")

    The :keyword:`async with` statement will wait for all tasks in the group to finish.
    While waiting, new tasks may still be added to the group
    (for example, by passing ``tg`` into one of the coroutines and calling ``tg.start_soon()`` in that coroutine).
    Once the last task has finished and the :keyword:`async with` block is exited, no new tasks may be added to the group.
    """

    __slots__ = ("__weakref__",)

    @abstractmethod
    async def __aenter__(self) -> Self:
        raise NotImplementedError

    @abstractmethod
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def start_soon(
        self,
        coro_func: Callable[[Unpack[_T_PosArgs]], Coroutine[Any, Any, _T]],
        /,
        *args: *_T_PosArgs,
        name: str | None = ...,
    ) -> None:
        """
        Schedules the creation of a new task in this task group.

        Parameters:
            coro_func: An async function.
            args: Positional arguments to be passed to `coro_func`. If you need to pass keyword arguments,
                  then use :func:`functools.partial`.
            name: Name of the task, for the purposes of introspection and debugging.
        """
        raise NotImplementedError

    @abstractmethod
    async def start(
        self,
        coro_func: Callable[[Unpack[_T_PosArgs]], Coroutine[Any, Any, _T]],
        /,
        *args: *_T_PosArgs,
        name: str | None = ...,
    ) -> Task[_T]:
        """
        Starts a new managed task in this task group. Blocks until the event loop starts the task.

        Warning:
            Unlike ``trio`` and ``anyio``, there is no ``task_status`` parameter.

        Parameters:
            coro_func: An async function.
            args: Positional arguments to be passed to `coro_func`. If you need to pass keyword arguments,
                  then use :func:`functools.partial`.
            name: Name of the task, for the purposes of introspection and debugging.

        Returns:
            the created task.
        """
        raise NotImplementedError


class ThreadsPortal(metaclass=ABCMeta):
    """
    An object that lets external threads run code in an asynchronous event loop.

    You must use it as a context manager *within* the event loop to start the portal::

        async with threads_portal:
            ...

    If the portal is not entered or exited, then all of the operations would throw a :exc:`RuntimeError` for the threads.
    """

    __slots__ = ("__weakref__",)

    @abstractmethod
    async def __aenter__(self) -> Self:
        raise NotImplementedError

    @abstractmethod
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def run_coroutine_soon(
        self,
        coro_func: Callable[_P, Awaitable[_T]],
        /,
        *args: _P.args,
        **kwargs: _P.kwargs,
    ) -> concurrent.futures.Future[_T]:
        """
        Run the given async function in the bound event loop thread. Thread-safe.

        Parameters:
            coro_func: An async function.
            args: Positional arguments to be passed to `coro_func`.
            kwargs: Keyword arguments to be passed to `coro_func`.

        Raises:
            RuntimeError: if the portal is shut down.
            RuntimeError: if you try calling this from inside the event loop thread, to avoid potential deadlocks.

        Returns:
            A future filled with the result of ``await coro_func(*args, **kwargs)``.
        """
        raise NotImplementedError

    def run_coroutine(self, coro_func: Callable[_P, Awaitable[_T]], /, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        """
        Run the given async function in the bound event loop thread, blocking until it is complete. Thread-safe.

        The default implementation is equivalent to::

            portal.run_coroutine_soon(coro_func, *args, **kwargs).result()

        Parameters:
            coro_func: An async function.
            args: Positional arguments to be passed to `coro_func`.
            kwargs: Keyword arguments to be passed to `coro_func`.

        Raises:
            concurrent.futures.CancelledError: The portal has been shut down while ``coro_func()`` was running
                                               and cancelled the task.
            RuntimeError: if the portal is shut down.
            RuntimeError: if you try calling this from inside the event loop thread, which would otherwise cause a deadlock.
            Exception: Whatever raises ``await coro_func(*args, **kwargs)``.

        Returns:
            Whatever returns ``await coro_func(*args, **kwargs)``.
        """
        return self.run_coroutine_soon(coro_func, *args, **kwargs).result()

    @abstractmethod
    def run_sync_soon(self, func: Callable[_P, _T], /, *args: _P.args, **kwargs: _P.kwargs) -> concurrent.futures.Future[_T]:
        """
        Executes a function in the event loop thread from a worker thread. Thread-safe.

        Parameters:
            func: A synchronous function.
            args: Positional arguments to be passed to `func`.
            kwargs: Keyword arguments to be passed to `func`.

        Raises:
            RuntimeError: if the portal is shut down.
            RuntimeError: if you try calling this from inside the event loop thread, to avoid potential deadlocks.

        Returns:
            A future filled with the result of ``func(*args, **kwargs)``.
        """
        raise NotImplementedError

    def run_sync(self, func: Callable[_P, _T], /, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        """
        Executes a function in the event loop thread from a worker thread. Thread-safe.

        The default implementation is equivalent to::

            portal.run_sync_soon(func, *args, **kwargs).result()

        Parameters:
            func: A synchronous function.
            args: Positional arguments to be passed to `func`.
            kwargs: Keyword arguments to be passed to `func`.

        Raises:
            RuntimeError: if the portal is shut down.
            RuntimeError: if you try calling this from inside the event loop thread, which would otherwise cause a deadlock.
            Exception: Whatever raises ``func(*args, **kwargs)``.

        Returns:
            Whatever returns ``func(*args, **kwargs)``.
        """
        return self.run_sync_soon(func, *args, **kwargs).result()


class AsyncBackend(metaclass=ABCMeta):
    """
    Asynchronous backend interface.

    It bridges the gap between asynchronous frameworks  (``asyncio``, ``trio``, or whatever) and EasyNetwork.
    """

    __slots__ = ("__weakref__",)

    @abstractmethod
    def bootstrap(
        self,
        coro_func: Callable[[Unpack[_T_PosArgs]], Coroutine[Any, Any, _T]],
        *args: *_T_PosArgs,
        runner_options: Mapping[str, Any] | None = ...,
    ) -> _T:
        """
        Runs an async function, and returns the result.

        Calling::

            backend.bootstrap(coro_func, *args)

        is equivalent to::

            await coro_func(*args)

        except that :meth:`bootstrap` can (and must) be called from a synchronous context.

        `runner_options` can be used to give additional parameters to the backend runner. For example::

            backend.bootstrap(coro_func, *args, runner_options={"loop_factory": uvloop.new_event_loop})

        would act as the following for :mod:`asyncio`::

            with asyncio.Runner(loop_factory=uvloop.new_event_loop) as runner:
                runner.run(coro_func(*args))

        Parameters:
            coro_func: An async function.
            args: Positional arguments to be passed to `coro_func`. If you need to pass keyword arguments,
                  then use :func:`functools.partial`.
            runner_options: Options for backend's runner.

        Returns:
            Whatever ``await coro_func(*args)`` returns.
        """
        raise NotImplementedError

    @abstractmethod
    async def coro_yield(self) -> None:
        """
        Explicitly introduce a breakpoint to suspend a task.

        This checks for cancellation and allows other tasks to be scheduled, without otherwise blocking.

        Note:
            The scheduler has the option of ignoring this and continuing to run the current task
            if it decides this is appropriate (e.g. for increased efficiency).
        """
        raise NotImplementedError

    @abstractmethod
    async def cancel_shielded_coro_yield(self) -> None:
        """
        Introduce a schedule point, but not a cancel point.

        Equivalent to (but probably more efficient than)::

            await backend.ignore_cancellation(backend.coro_yield())
        """
        raise NotImplementedError

    @abstractmethod
    def get_cancelled_exc_class(self) -> type[BaseException]:
        """
        Returns the current async library's cancellation exception class.

        Returns:
            An exception class.
        """
        raise NotImplementedError

    @abstractmethod
    async def ignore_cancellation(self, coroutine: Awaitable[_T_co]) -> _T_co:
        """
        Protect a :term:`coroutine` from being cancelled.

        The statement::

            res = await backend.ignore_cancellation(something())

        is equivalent to::

            res = await something()

        `except` that if the coroutine containing it is cancelled, the task running in ``something()`` is not cancelled.
        """
        raise NotImplementedError

    @abstractmethod
    def open_cancel_scope(self, *, deadline: float = ...) -> CancelScope:
        """
        Open a new cancel scope. See :meth:`move_on_after` for details.

        Parameters:
            deadline: absolute time to stop waiting. Defaults to :data:`math.inf`.

        Returns:
            a new cancel scope.
        """
        raise NotImplementedError

    def timeout(self, delay: float) -> AbstractContextManager[CancelScope, None]:
        """
        Returns a :term:`context manager` that can be used to limit the amount of time spent waiting on something.

        This function and :meth:`move_on_after` are similar in that both create a context manager with a given timeout,
        and if the timeout expires then both will cause ``backend.get_cancelled_exc_class()`` to be raised within the scope.
        The difference is that when the exception reaches :meth:`move_on_after`, it is caught and discarded. When it reaches
        :meth:`timeout`, then it is caught and :exc:`TimeoutError` is raised in its place.

        Parameters:
            delay: number of seconds to wait.

        Returns:
            a :term:`context manager`
        """
        return _timeout_scope(self.move_on_after(delay))

    def timeout_at(self, deadline: float) -> AbstractContextManager[CancelScope, None]:
        """
        Returns a :term:`context manager` that can be used to limit the amount of time spent waiting on something.

        This function and :meth:`move_on_at` are similar in that both create a context manager with a given timeout,
        and if the timeout expires then both will cause ``backend.get_cancelled_exc_class()`` to be raised within the scope.
        The difference is that when the exception reaches :meth:`move_on_at`, it is caught and discarded. When it reaches
        :meth:`timeout_at`, then it is caught and :exc:`TimeoutError` is raised in its place.

        Parameters:
            deadline: absolute time to stop waiting.

        Returns:
            a :term:`context manager`
        """
        return _timeout_scope(self.move_on_at(deadline))

    def move_on_after(self, delay: float) -> CancelScope:
        """
        Returns a new :class:`CancelScope` that can be used to limit the amount of time spent waiting on something.
        The deadline is set to now + `delay`.

        Example::

            async def long_running_operation(backend):
                await backend.sleep(3600)  # 1 hour

            async def main():
                ...

                with backend.move_on_after(10):
                    await long_running_operation(backend)

                print("After at most 10 seconds.")

        If ``long_running_operation`` takes more than 10 seconds to complete, the context manager will cancel the current task
        and handle the resulting ``backend.get_cancelled_exc_class()`` exception internally.

        Parameters:
            delay: number of seconds to wait. If `delay` is :data:`math.inf`,
                   no time limit will be applied; this can be useful if the delay is unknown when the context manager is created.
                   In either case, the context manager can be rescheduled after creation using :meth:`CancelScope.reschedule`.

        Returns:
            a new cancel scope.
        """
        return self.open_cancel_scope(deadline=self.current_time() + delay)

    def move_on_at(self, deadline: float) -> CancelScope:
        """
        Similar to :meth:`move_on_after`, except `deadline` is the absolute time to stop waiting, or :data:`math.inf`.

        Example::

            async def long_running_operation(backend):
                await backend.sleep(3600)  # 1 hour

            async def main():
                ...

                deadline = backend.current_time() + 10
                with backend.move_on_at(deadline):
                    await long_running_operation(backend)

                print("After at most 10 seconds.")

        Parameters:
            deadline: absolute time to stop waiting.

        Returns:
            a new cancel scope.
        """
        return self.open_cancel_scope(deadline=deadline)

    @abstractmethod
    def current_time(self) -> float:
        """
        Returns the current time according to the scheduler clock.

        Returns:
            The current time.
        """
        raise NotImplementedError

    @abstractmethod
    async def sleep(self, delay: float) -> None:
        """
        Pause execution of the current task for the given number of seconds.

        Parameters:
            delay: The number of seconds to sleep. May be zero to insert a checkpoint without actually blocking.

        Raises:
            ValueError: if `delay` is negative or NaN.
        """
        raise NotImplementedError

    @abstractmethod
    async def sleep_forever(self) -> NoReturn:
        """
        Pause execution of the current task forever (or at least until cancelled).

        Equivalent to (but probably more efficient than)::

            await backend.sleep(math.inf)
        """
        raise NotImplementedError

    async def sleep_until(self, deadline: float) -> None:
        """
        Pause execution of the current task until the given time.

        The difference between :meth:`sleep` and :meth:`sleep_until` is that the former takes a relative time and the latter
        takes an absolute time (as returned by :meth:`current_time`).

        Parameters:
            deadline: The time at which we should wake up again. May be in the past, in which case this function
                      executes a checkpoint but does not block.
        """
        return await self.sleep(max(deadline - self.current_time(), 0))

    async def gather(self, *coroutines: Awaitable[_T_co]) -> list[_T_co]:
        """
        Run awaitable objects in the `coroutines` sequence concurrently.

        Parameters:
            coroutines: any awaitable object.

        Returns:
            If all awaitables are completed successfully, the result is an aggregate list of returned values.
            The order of result values corresponds to the order of awaitables in `coroutines`.

        Raises:
            ExceptionGroup: If one or more awaitable(s) fails.
        """

        if not coroutines:
            # Fast path.
            return []

        from ..._utils import remove_traceback_frames_in_place

        async def _await(coro: Awaitable[_T_co]) -> _T_co:
            try:
                return await coro
            except BaseException as exc:
                remove_traceback_frames_in_place(exc, 1)
                raise
            finally:
                del coro

        coro_to_task: dict[Awaitable[_T_co], Task[_T_co]] = {}

        children: list[Task[_T_co]] = []

        async with self.create_task_group() as task_group:
            for coro in coroutines:
                if coro in coro_to_task:
                    task = coro_to_task[coro]
                else:
                    task = await self.ignore_cancellation(task_group.start(_await, coro))
                    coro_to_task[coro] = task
                children.append(task)

            coro_to_task.clear()

        # task_group should raise an ExceptionGroup if one of the coroutine raises an exception
        # At this point, all the tasks should be done and join() would neither block nor raise.
        assert all(child.done() for child in children)  # nosec assert_used
        return [await child.join() for child in children]

    @abstractmethod
    def create_task_group(self) -> TaskGroup:
        """
        Creates a task group.

        The most common use is as an :term:`asynchronous context manager`::

            async with backend.create_task_group() as task_group:
                ...

        Returns:
            A new task group.
        """
        raise NotImplementedError

    @abstractmethod
    def get_current_task(self) -> TaskInfo:
        """
        Return the current task.

        Returns:
            a representation of the current task.
        """
        raise NotImplementedError

    async def getaddrinfo(
        self,
        host: bytes | str | None,
        port: bytes | str | int | None,
        family: int = 0,
        type: int = 0,
        proto: int = 0,
        flags: int = 0,
    ) -> Sequence[tuple[int, int, int, str, tuple[str, int] | tuple[str, int, int, int] | tuple[int, bytes]]]:
        """
        Asynchronous version of :func:`socket.getaddrinfo`.
        """
        from ..._utils import make_callback

        getaddrinfo = make_callback(_socket.getaddrinfo, host, port, family=family, type=type, proto=proto, flags=flags)

        return await self.run_in_thread(getaddrinfo, abandon_on_cancel=True)

    async def getnameinfo(
        self,
        sockaddr: tuple[str, int] | tuple[str, int, int, int],
        flags: int = 0,
    ) -> tuple[str, str]:
        """
        Asynchronous version of :func:`socket.getnameinfo`.
        """
        from ..._utils import make_callback

        getnameinfo = make_callback(_socket.getnameinfo, sockaddr, flags)

        return await self.run_in_thread(getnameinfo, abandon_on_cancel=True)

    @abstractmethod
    async def create_tcp_connection(
        self,
        host: str,
        port: int,
        *,
        local_address: tuple[str, int] | None = ...,
        happy_eyeballs_delay: float | None = ...,
    ) -> _transports.AsyncStreamTransport:
        """
        Opens a connection using the TCP/IP protocol.

        Parameters:
            host: The host IP/domain name.
            port: Port of connection.
            local_address: If given, is a ``(local_host, local_port)`` tuple used to bind the socket locally.
            happy_eyeballs_delay: If given, is the "Connection Attempt Delay" as defined in :rfc:`8305`.

        Raises:
            ConnectionError: Cannot connect to `host` with the given `port`.
            OSError: unrelated OS error occurred.

        Returns:
            A stream socket.
        """
        raise NotImplementedError

    async def create_unix_stream_connection(
        self,
        path: str | bytes,
        *,
        local_path: str | bytes | None = None,
    ) -> _transports.AsyncStreamTransport:  # pragma: no cover
        """
        Opens a connection to a Unix stream socket.

        .. versionadded:: 1.1

        Parameters:
            path: Path of the socket to which the connection is made.
            local_path: If given, is a Unix socket address used to bind the socket locally.

        Raises:
            ConnectionError: Cannot connect to `path`.
            OSError: unrelated OS error occurred.

        Returns:
            A stream socket.
        """
        raise NotImplementedError

    @abstractmethod
    async def wrap_stream_socket(self, socket: _socket.socket) -> _transports.AsyncStreamTransport:
        """
        Wraps an already connected :data:`~socket.SOCK_STREAM` socket into an asynchronous stream socket.

        Important:
            The returned stream socket takes the ownership of `socket`.

            You should use :meth:`.AsyncStreamTransport.aclose` to close the socket.

        Parameters:
            socket: The socket to wrap.

        Raises:
            ValueError: Invalid socket type or family.

        Returns:
            A stream socket.
        """
        raise NotImplementedError

    @abstractmethod
    async def create_tcp_listeners(
        self,
        host: str | Sequence[str] | None,
        port: int,
        backlog: int,
        *,
        reuse_port: bool = ...,
    ) -> Sequence[_transports.AsyncListener[_transports.AsyncStreamTransport]]:
        """
        Opens listener sockets for TCP connections.

        Parameters:
            host: Can be set to several types which determine where the server would be listening:

                  * If `host` is a string, the TCP server is bound to a single network interface specified by `host`.

                  * If `host` is a sequence of strings, the TCP server is bound to all network interfaces specified by the sequence.

                  * If `host` is :data:`None`, all interfaces are assumed and a list of multiple sockets will be returned
                    (most likely one for IPv4 and another one for IPv6).
            port: specify which port the server should listen on. If the value is ``0``, a random unused port will be selected
                  (note that if `host` resolves to multiple network interfaces, a different random port will be selected
                  for each interface).
            backlog: is the maximum number of queued connections passed to :class:`~socket.socket.listen`.
            reuse_port: tells the kernel to allow this endpoint to be bound to the same port as other existing endpoints
                        are bound to, so long as they all set this flag when being created.
                        This option is not supported on Windows.

        Raises:
            OSError: unrelated OS error occurred.

        Returns:
            A sequence of listener sockets.
        """
        raise NotImplementedError

    async def create_unix_stream_listener(
        self,
        path: str | bytes,
        backlog: int,
        *,
        mode: int | None = None,
    ) -> _transports.AsyncListener[_transports.AsyncStreamTransport]:  # pragma: no cover
        """
        Opens a listener socket for Unix stream connections.

        .. versionadded:: 1.1

        Parameters:
            path: Path of the socket.
            backlog: is the maximum number of queued connections passed to :class:`~socket.socket.listen`.
            mode: Permissions to set on the socket.

        Raises:
            OSError: unrelated OS error occurred.

        Returns:
            A listener socket.
        """
        raise NotImplementedError

    @abstractmethod
    async def create_udp_endpoint(
        self,
        remote_host: str,
        remote_port: int,
        *,
        local_address: tuple[str, int] | None = ...,
        family: int = ...,
    ) -> _transports.AsyncDatagramTransport:
        """
        Opens an endpoint using the UDP/IP protocol.

        Parameters:
            remote_host: The host IP/domain name.
            remote_port: Port of connection.
            local_address: If given, is a ``(local_host, local_port)`` tuple used to bind the socket locally.
            family: The address family. Should be any of ``AF_UNSPEC``, ``AF_INET`` or ``AF_INET6``.

        Raises:
            OSError: unrelated OS error occurred.

        Returns:
            A datagram socket.
        """
        raise NotImplementedError

    async def create_unix_datagram_endpoint(
        self,
        path: str | bytes,
        *,
        local_path: str | bytes | None = None,
    ) -> _transports.AsyncDatagramTransport:  # pragma: no cover
        """
        Opens an endpoint to a Unix datagram socket.

        .. versionadded:: 1.1

        Parameters:
            path: Path of the socket to which the connection is made.
            local_path: If given, is a Unix socket address used to bind the socket locally.

        Raises:
            OSError: unrelated OS error occurred.

        Returns:
            A datagram socket.
        """
        raise NotImplementedError

    @abstractmethod
    async def wrap_connected_datagram_socket(self, socket: _socket.socket) -> _transports.AsyncDatagramTransport:
        """
        Wraps an already connected :data:`~socket.SOCK_DGRAM` socket into an asynchronous datagram socket.

        Important:
            The returned stream socket takes the ownership of `socket`.

            You should use :meth:`.AsyncDatagramTransport.aclose` to close the socket.

        Parameters:
            socket: The socket to wrap.

        Raises:
            ValueError: Invalid socket type or family.

        Returns:
            A datagram socket.
        """
        raise NotImplementedError

    @abstractmethod
    async def create_udp_listeners(
        self,
        host: str | Sequence[str] | None,
        port: int,
        *,
        reuse_port: bool = ...,
    ) -> Sequence[_transports.AsyncDatagramListener[tuple[Any, ...]]]:
        """
        Opens UDP endpoints.

        Parameters:
            host: Can be set to several types which determine where the server would be listening:

                  * If `host` is a string, the UDP server is bound to a single network interface specified by `host`.

                  * If `host` is a sequence of strings, the UDP server is bound to all network interfaces specified by the sequence.

                  * If `host` is :data:`None`, all interfaces are assumed and a list of multiple sockets will be returned
                    (most likely one for IPv4 and another one for IPv6).
            port: specify which port the server should listen on. If the value is ``0``, a random unused port will be selected
                  (note that if `host` resolves to multiple network interfaces, a different random port will be selected
                  for each interface).
            reuse_port: If :data:`True`, sets the :data:`~socket.SO_REUSEPORT` socket option if supported.

        Raises:
            OSError: unrelated OS error occurred.

        Returns:
            A sequence of datagram listener sockets.
        """
        raise NotImplementedError

    async def create_unix_datagram_listener(
        self,
        path: str | bytes,
        *,
        mode: int | None = None,
    ) -> _transports.AsyncDatagramListener[str | bytes]:  # pragma: no cover
        """
        Opens a Unix datagram endpoint.

        .. versionadded:: 1.1

        Parameters:
            path: Path of the socket.
            mode: Permissions to set on the socket.

        Raises:
            OSError: unrelated OS error occurred.

        Returns:
            A datagram listener socket.
        """
        raise NotImplementedError

    @abstractmethod
    def create_lock(self) -> ILock:
        """
        Creates a Lock object for inter-task synchronization.

        Returns:
            A new Lock.
        """
        raise NotImplementedError

    def create_fair_lock(self) -> ILock:
        """
        Creates a Lock object for inter-task synchronization where tasks are guaranteed to acquire the lock in strict
        first-come-first-served order.

        This means that it always goes to the task which has been waiting longest.

        .. versionadded:: 1.1

        Returns:
            A new fair Lock.
        """
        from ._common.fair_lock import FairLock

        return FairLock(self)

    @abstractmethod
    def create_event(self) -> IEvent:
        """
        Creates an Event object for inter-task synchronization.

        Returns:
            A new Event.
        """
        raise NotImplementedError

    @abstractmethod
    def create_condition_var(self, lock: ILock | None = ...) -> ICondition:
        """
        Creates a Condition variable object for inter-task synchronization.

        If `lock` is given and not :data:`None`, it should be a lock created by :meth:`create_lock`.
        While it is guaranteed to work with a lock from :meth:`create_lock`, it can be any other implementation
        (such as the lock returned by :meth:`create_fair_lock`), but it can also refuse other implementations.

        Generic code should expect the function to fail::

            try:
                cond = backend.create_condition_var(backend.create_fair_lock())
            except TypeError:
                # Cannot use a fair lock. Use the default implementation instead.
                cond = backend.create_condition_var()

        Parameters:
            lock: The lock instance to use under the hood.

        Raises:
            TypeError: `lock` type is not supported.

        Returns:
            A new Condition.
        """
        raise NotImplementedError

    @abstractmethod
    async def run_in_thread(
        self,
        func: Callable[[*_T_PosArgs], _T],
        /,
        *args: *_T_PosArgs,
        abandon_on_cancel: bool = ...,
    ) -> _T:
        """
        Executes a synchronous function in a worker thread.

        This is useful to execute a long-running (or temporarily blocking) function and let other tasks run.

        From inside the worker thread, you can get back into the scheduler loop using a :class:`ThreadsPortal`.
        See :meth:`create_threads_portal` for details.

        Cancellation handling:
            Because there is no way to "cancel" an arbitrary function call in an OS thread,
            once the job is started:

            * If `abandon_on_cancel` is False (the default), any cancellation requests will be discarded.

            * If `abandon_on_cancel` is True, the task will notify the thread to stop (if possible) then will bail out.

        Warning:
            Due to the current coroutine implementation, `func` should not raise a :exc:`StopIteration`.
            This can lead to unexpected (and unwanted) behavior.

        Parameters:
            func: A synchronous function.
            args: Positional arguments to be passed to `func`. If you need to pass keyword arguments,
                  then use :func:`functools.partial`.
            abandon_on_cancel: Whether or not to abort task on cancellation request.

        Raises:
            Exception: Whatever ``func(*args)`` raises.

        Returns:
            Whatever ``func(*args)`` returns.
        """
        raise NotImplementedError

    @abstractmethod
    def create_threads_portal(self) -> ThreadsPortal:
        """
        Creates a portal for executing functions in the event loop thread for use in external threads.

        Use this function in asynchronous code when you need to allow external threads access to the event loop
        where your asynchronous code is currently running.

        Raises:
            RuntimeError: not called in the event loop thread.

        Returns:
            a new thread portal.
        """
        raise NotImplementedError


@dataclasses.dataclass(frozen=True, slots=True)
class _timeout_scope:
    scope: CancelScope

    def __enter__(self) -> CancelScope:
        return self.scope.__enter__()

    def __exit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None) -> None:
        try:
            suppressed = self.scope.__exit__(exc_type, exc_val, exc_tb)
            if suppressed and self.scope.cancelled_caught():
                raise TimeoutError("timed out") from exc_val
        finally:
            del self, exc_val, exc_tb  # Prevent cyclic reference.
