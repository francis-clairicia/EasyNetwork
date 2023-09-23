# Copyright 2021-2023, Francis Clairicia-Rose-Claire-Josephine
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
"""Asynchronous backend engine interfaces module"""

from __future__ import annotations

__all__ = [
    "AcceptedSocket",
    "AsyncBackend",
    "AsyncBaseSocketAdapter",
    "AsyncDatagramSocketAdapter",
    "AsyncListenerSocketAdapter",
    "AsyncStreamSocketAdapter",
    "ICondition",
    "IEvent",
    "ILock",
    "Task",
    "TaskGroup",
    "ThreadsPortal",
    "TimeoutHandle",
]

import contextvars
import math
from abc import ABCMeta, abstractmethod
from collections.abc import Awaitable, Callable, Coroutine, Iterable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING, Any, Generic, NoReturn, ParamSpec, Protocol, Self, TypeVar

if TYPE_CHECKING:
    import concurrent.futures
    import socket as _socket
    import ssl as _typing_ssl
    from types import TracebackType

    from ...tools.socket import ISocket


_P = ParamSpec("_P")
_T = TypeVar("_T")
_T_co = TypeVar("_T_co", covariant=True)


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

    async def __aenter__(self) -> Any:  # pragma: no cover
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
        /,
    ) -> bool | None:  # pragma: no cover
        ...

    async def acquire(self) -> Any:  # pragma: no cover
        """
        Acquires the lock.

        This method waits until the lock is *unlocked*, sets it to *locked*.

        When more than one coroutine is blocked in :meth:`acquire` waiting for the lock to be unlocked,
        only one coroutine eventually proceeds.
        """
        ...

    def release(self) -> None:  # pragma: no cover
        """
        Releases the lock.

        When the lock is locked, reset it to unlocked and return.

        Raises:
            RuntimeError: the lock is *unlocked* or the task does not have the lock ownership.
        """
        ...

    def locked(self) -> bool:  # pragma: no cover
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

    async def wait(self) -> Any:  # pragma: no cover
        """
        Blocks until the internal flag value becomes :data:`True`.

        If it is already :data:`True`, then this method returns immediately.
        """
        ...

    def set(self) -> None:  # pragma: no cover
        """
        Sets the internal flag value to :data:`True`, and wake any waiting tasks.
        """
        ...

    def is_set(self) -> bool:  # pragma: no cover
        """
        Returns:
            the current value of the internal flag.
        """
        ...


class ICondition(ILock, Protocol):
    """
    A classic condition variable, similar to :class:`threading.Condition`.

    """

    def notify(self, n: int = ..., /) -> None:  # pragma: no cover
        """
        Wake one or more tasks that are blocked in :meth:`wait`.
        """
        ...

    def notify_all(self) -> None:  # pragma: no cover
        """
        Wake all tasks that are blocked in :meth:`wait`.
        """
        ...

    async def wait(self) -> Any:  # pragma: no cover
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

    @abstractmethod
    def done(self) -> bool:
        """
        Returns :data:`True` if the Task is done.

        A Task is *done* when the wrapped coroutine either returned a value, raised an exception, or the Task was cancelled.

        Returns:
            The Task state.
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
        Returns :data:`True` if the Task is *cancelled*.

        The Task is *cancelled* when the cancellation was requested with :meth:`cancel` and the wrapped coroutine propagated
        the ``backend.get_cancelled_exc_class()`` exception thrown into it.

        Returns:
            the cancellation state.
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


class SystemTask(Task[_T_co]):
    """
    A :class:`SystemTask` is a :class:`Task` that runs concurrently with the current root task.
    """

    __slots__ = ()

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


class TaskGroup(metaclass=ABCMeta):
    """
    Groups several asynchronous tasks together.

    Example::

        async def main():
            async with backend.create_task_group() as tg:
                task1 = tg.start_soon(some_coro)
                task2 = tg.start_soon(another_coro)
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
        coro_func: Callable[..., Coroutine[Any, Any, _T]],
        /,
        *args: Any,
        context: contextvars.Context | None = ...,
    ) -> Task[_T]:
        """
        Starts a new task in this task group.

        Parameters:
            coro_func: An async function.
            args: Positional arguments to be passed to `coro_func`. If you need to pass keyword arguments,
                  then use :func:`functools.partial`.
            context: If given, it must be a :class:`contextvars.Context` instance in which the coroutine should be executed.
                     If the framework does not support contexts (or does not use them), it must simply ignore this parameter.

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


class AsyncBaseSocketAdapter(metaclass=ABCMeta):
    """
    Base class for asynchronous socket adapters.
    """

    __slots__ = ("__weakref__",)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Calls :meth:`aclose`."""
        await self.aclose()

    @abstractmethod
    def is_closing(self) -> bool:
        """
        Checks if the socket is closed or in the process of being closed.
        """
        raise NotImplementedError

    @abstractmethod
    async def aclose(self) -> None:
        """
        Closes the socket.

        Warning:
            :meth:`aclose` performs a graceful close.

            If :meth:`aclose` is cancelled, the socket is closed abruptly.
        """
        raise NotImplementedError

    @abstractmethod
    def socket(self) -> ISocket:
        """
        Returns the socket instance for low-level operations (such as ``socket.setsockopt()``).

        Returns:
            An object implementing the :protocol:`.ISocket` interface.
        """
        raise NotImplementedError


class AsyncStreamSocketAdapter(AsyncBaseSocketAdapter):
    """
    A stream-oriented socket interface.
    """

    __slots__ = ()

    @abstractmethod
    async def recv(self, bufsize: int, /) -> bytes:
        """
        Similar to :meth:`socket.socket.recv`, except asynchronous.

        Parameters:
            bufsize: The maximum amount of bytes to receive.
        """
        raise NotImplementedError

    @abstractmethod
    async def sendall(self, data: bytes, /) -> None:
        """
        Similar to :meth:`socket.socket.sendall`, except asynchronous.

        Parameters:
            data: The bytes to send.
        """
        raise NotImplementedError

    async def sendall_fromiter(self, iterable_of_data: Iterable[bytes], /) -> None:
        """
        An efficient way to send a bunch of data via the socket.

        Currently, the default implementation concatenates the arguments and
        calls :meth:`sendall` on the result.

        Parameters:
            iterable_of_data: An :term:`iterable` yielding the bytes to send.
        """
        await self.sendall(b"".join(iterable_of_data))

    @abstractmethod
    async def send_eof(self) -> None:
        """
        Send an end-of-file indication on this stream, if possible. Similar to :meth:`socket.socket.shutdown`.
        """
        raise NotImplementedError


class AsyncDatagramSocketAdapter(AsyncBaseSocketAdapter):
    """
    A datagram-oriented socket interface.
    """

    __slots__ = ()

    @abstractmethod
    async def recvfrom(self, bufsize: int, /) -> tuple[bytes, tuple[Any, ...]]:
        """
        Similar to :meth:`socket.socket.recvfrom`, except asynchronous.

        Parameters:
            bufsize: The maximum amount of bytes to receive.
        """
        raise NotImplementedError

    @abstractmethod
    async def sendto(self, data: bytes, address: tuple[Any, ...] | None, /) -> None:
        """
        Similar to :meth:`socket.socket.sendto`, except asynchronous.

        Parameters:
            data: The bytes to send.
        """
        raise NotImplementedError


class AsyncListenerSocketAdapter(AsyncBaseSocketAdapter):
    """
    An interface for socket listeners.
    """

    __slots__ = ()

    @abstractmethod
    async def accept(self) -> AcceptedSocket:
        """
        Similar to :meth:`socket.socket.accept`, except asynchronous.

        The returned object is not directly usable for stream operations. You must call :meth:`AcceptedSocket.connect` on it::

            accepted_socket = await listener.accept()
            stream_socket = await accepted_socket.connect()

        This helps to improve interoperability between tasks::

            async def echo_handler(stream_socket):
                async with stream_socket:
                    while True:
                        data = await stream_socket.recv(1024)
                        if not data:
                            break
                        await stream_socket.sendall(data)

            async def serve(listener, task_group):

                # Coroutine that waits for the connection to be fully etablished
                # (e.g. Perform SSL/TLS handshake if necessary.)
                async def connect_and_run(accepted_socket):
                    stream_socket = await accepted_socket.connect()
                    # The connection is up; call the real handler
                    task_group.start_soon(echo_handler, stream_socket)

                while True:
                    accepted_socket = await listener.accept()

                    # Run 'accepted_socket.connect()' in another task.
                    task_group.start_soon(connect_and_run, accepted_socket)

        In this case, ``listener.accept()`` will simply dequeue the pending connections without waiting for
        a ready stream interface to become available.

        Returns:
            The accepted socket.
        """
        raise NotImplementedError


class AcceptedSocket(metaclass=ABCMeta):
    """
    An object representing an accepted socket from an :class:`AsyncListenerSocketAdapter`.
    """

    __slots__ = ()

    @abstractmethod
    async def connect(self) -> AsyncStreamSocketAdapter:
        """
        Wraps the accepted socket into an asynchronous stream socket, and perform connection initialization if necessary.

        For example, an SSL/TLS stream would perform a TLS handshake.

        Returns:
            A stream socket.
        """
        raise NotImplementedError


class TimeoutHandle(metaclass=ABCMeta):
    """
    Interface to deal with an actual timeout scope.

    See :meth:`AsyncBackend.move_on_after` for details.
    """

    __slots__ = ()

    @abstractmethod
    def when(self) -> float:
        """
        Returns the current deadline.

        Returns:
            the absolute time in seconds. :data:`math.inf` if the current deadline is not set.
            A negative value can be returned.
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

    @abstractmethod
    def expired(self) -> bool:
        """
        Returns whether the context manager has exceeded its deadline (expired).

        Returns:
            the timeout state.
        """
        raise NotImplementedError

    @property
    def deadline(self) -> float:
        """
        A read-write attribute to simplify the timeout management.

        For example, this statement::

            handle.deadline += 30

        is equivalent to::

            handle.reschedule(handle.when() + 30)

        It is also possible to remove the timeout by deleting the attribute::

            del handle.deadline
        """
        return self.when()

    @deadline.setter
    def deadline(self, value: float) -> None:
        self.reschedule(value)

    @deadline.deleter
    def deadline(self) -> None:
        self.reschedule(math.inf)


class AsyncBackend(metaclass=ABCMeta):
    """
    Asynchronous backend interface.

    It bridges the gap between asynchronous frameworks  (``asyncio``, ``trio``, or whatever) and EasyNetwork.
    """

    __slots__ = ("__weakref__",)

    @abstractmethod
    def bootstrap(
        self,
        coro_func: Callable[..., Coroutine[Any, Any, _T]],
        *args: Any,
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

            with asyncio.Runner(loop_factory=uvloop.new_event_loop):
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
    async def ignore_cancellation(self, coroutine: Coroutine[Any, Any, _T_co]) -> _T_co:
        """
        Protect a :term:`coroutine` from being cancelled.

        The statement::

            res = await backend.ignore_cancellation(something())

        is equivalent to::

            res = await something()

        `except` that if the coroutine containing it is cancelled, the Task running in ``something()`` is not cancelled.

        Important:
            Depending on the implementation, the coroutine may or may not be executed in the same :class:`contextvars.Context`.

        """
        raise NotImplementedError

    @abstractmethod
    def timeout(self, delay: float) -> AbstractAsyncContextManager[TimeoutHandle]:
        """
        Returns an :term:`asynchronous context manager` that can be used to limit the amount of time spent waiting on something.

        This function and :meth:`move_on_after` are similar in that both create a context manager with a given timeout,
        and if the timeout expires then both will cause ``backend.get_cancelled_exc_class()`` to be raised within the scope.
        The difference is that when the exception reaches :meth:`move_on_after`, it is caught and discarded. When it reaches
        :meth:`timeout`, then it is caught and :exc:`TimeoutError` is raised in its place.

        Parameters:
            delay: number of seconds to wait.

        Returns:
            an :term:`asynchronous context manager`
        """
        raise NotImplementedError

    @abstractmethod
    def timeout_at(self, deadline: float) -> AbstractAsyncContextManager[TimeoutHandle]:
        """
        Returns an :term:`asynchronous context manager` that can be used to limit the amount of time spent waiting on something.

        This function and :meth:`move_on_at` are similar in that both create a context manager with a given timeout,
        and if the timeout expires then both will cause ``backend.get_cancelled_exc_class()`` to be raised within the scope.
        The difference is that when the exception reaches :meth:`move_on_at`, it is caught and discarded. When it reaches
        :meth:`timeout_at`, then it is caught and :exc:`TimeoutError` is raised in its place.

        Parameters:
            deadline: absolute time to stop waiting.

        Returns:
            an :term:`asynchronous context manager`
        """
        raise NotImplementedError

    @abstractmethod
    def move_on_after(self, delay: float) -> AbstractAsyncContextManager[TimeoutHandle]:
        """
        Returns an :term:`asynchronous context manager` that can be used to limit the amount of time spent waiting on something.
        The deadline is set to now + `delay`.

        Example::

            async def long_running_operation(backend):
                await backend.sleep(3600)  # 1 hour

            async def main():
                ...

                async with backend.move_on_after(10):
                    await long_running_operation(backend)

                print("After at most 10 seconds.")

        If ``long_running_operation`` takes more than 10 seconds to complete, the context manager will cancel the current task
        and handle the resulting ``backend.get_cancelled_exc_class()`` exception internally.

        Parameters:
            delay: number of seconds to wait. If `delay` is :data:`math.inf`,
                   no time limit will be applied; this can be useful if the delay is unknown when the context manager is created.
                   In either case, the context manager can be rescheduled after creation using :meth:`TimeoutHandle.reschedule`.

        Returns:
            an :term:`asynchronous context manager`
        """
        raise NotImplementedError

    @abstractmethod
    def move_on_at(self, deadline: float) -> AbstractAsyncContextManager[TimeoutHandle]:
        """
        Similar to :meth:`move_on_after`, except `deadline` is the absolute time to stop waiting, or :data:`math.inf`.

        Example::

            async def long_running_operation(backend):
                await backend.sleep(3600)  # 1 hour

            async def main():
                ...

                deadline = backend.current_time() + 10
                async with backend.move_on_at(deadline):
                    await long_running_operation(backend)

                print("After at most 10 seconds.")

        Parameters:
            deadline: absolute time to stop waiting.

        Returns:
            an :term:`asynchronous context manager`
        """
        raise NotImplementedError

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

    @abstractmethod
    def spawn_task(
        self,
        coro_func: Callable[..., Coroutine[Any, Any, _T]],
        /,
        *args: Any,
        context: contextvars.Context | None = ...,
    ) -> SystemTask[_T]:
        """
        Starts a new "system" task.

        It is a background task that runs concurrently with the current root task.

        Parameters:
            coro_func: An async function.
            args: Positional arguments to be passed to `coro_func`.  If you need to pass keyword arguments,
                  then use :func:`functools.partial`.
            context: If given, it must be a :class:`contextvars.Context` instance in which the coroutine should be executed.
                     If the framework does not support contexts (or does not use them), it must simply ignore this parameter.

        Returns:
            the created task.
        """
        raise NotImplementedError

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
    async def create_tcp_connection(
        self,
        host: str,
        port: int,
        *,
        local_address: tuple[str, int] | None = ...,
        happy_eyeballs_delay: float | None = ...,
    ) -> AsyncStreamSocketAdapter:
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

    async def create_ssl_over_tcp_connection(
        self,
        host: str,
        port: int,
        ssl_context: _typing_ssl.SSLContext,
        *,
        server_hostname: str | None,
        ssl_handshake_timeout: float,
        ssl_shutdown_timeout: float,
        local_address: tuple[str, int] | None = ...,
        happy_eyeballs_delay: float | None = ...,
    ) -> AsyncStreamSocketAdapter:
        """
        Opens an SSL/TLS stream connection on top of the TCP/IP protocol.

        Parameters:
            host: The host IP/domain name.
            port: Port of connection.
            ssl_context: TLS connection configuration (see :mod:`ssl` module).
            server_hostname: sets or overrides the hostname that the target server's certificate will be matched against.
                             By default, `host` is used.
            ssl_handshake_timeout: the time in seconds to wait for the TLS handshake to complete.
            ssl_shutdown_timeout: the time in seconds to wait for the SSL shutdown to complete before aborting the connection.
            local_address: If given, is a ``(local_host, local_port)`` tuple used to bind the socket locally.
            happy_eyeballs_delay: If given, is the "Connection Attempt Delay" as defined in :rfc:`8305`.

        Raises:
            ConnectionError: Cannot connect to `host` with the given `port`.
            ssl.SSLError: Error in the TLS handshake (invalid certificate, ciphers, etc.).
            OSError: unrelated OS error occurred.

        Returns:
            A stream socket.
        """
        raise NotImplementedError("SSL/TLS is not supported by this backend")

    @abstractmethod
    async def wrap_tcp_client_socket(self, socket: _socket.socket) -> AsyncStreamSocketAdapter:
        """
        Wraps an already connected over TCP/IP protocol socket into an asynchronous stream socket.

        Important:
            The returned stream socket takes the ownership of `socket`.

            You should use :meth:`AsyncStreamSocketAdapter.aclose` to close the socket.

        Parameters:
            socket: The socket to wrap.

        Raises:
            ValueError: Invalid socket type or family.

        Returns:
            A stream socket.
        """
        raise NotImplementedError

    async def wrap_ssl_over_tcp_client_socket(
        self,
        socket: _socket.socket,
        ssl_context: _typing_ssl.SSLContext,
        *,
        server_hostname: str,
        ssl_handshake_timeout: float,
        ssl_shutdown_timeout: float,
    ) -> AsyncStreamSocketAdapter:
        """
        Wraps an already connected over TCP/IP protocol socket into an asynchronous stream socket in a SSL/TLS context.

        Important:
            The returned stream socket takes the ownership of `socket`.

            You should use :meth:`AsyncStreamSocketAdapter.aclose` to close the socket.

        Parameters:
            socket: The socket to wrap.
            ssl_context: TLS connection configuration (see :mod:`ssl` module).
            server_hostname: sets the hostname that the target server's certificate will be matched against.
            ssl_handshake_timeout: the time in seconds to wait for the TLS handshake to complete.
            ssl_shutdown_timeout: the time in seconds to wait for the SSL shutdown to complete before aborting the connection.

        Raises:
            ConnectionError: TLS handshake failed to connect to the remote.
            ssl.SSLError: Error in the TLS handshake (invalid certificate, ciphers, etc.).
            OSError: unrelated OS error occurred.
            ValueError: Invalid socket type or family.

        Returns:
            A stream socket.
        """
        raise NotImplementedError("SSL/TLS is not supported by this backend")

    @abstractmethod
    async def create_tcp_listeners(
        self,
        host: str | Sequence[str] | None,
        port: int,
        backlog: int,
        *,
        reuse_port: bool = ...,
    ) -> Sequence[AsyncListenerSocketAdapter]:
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
            backlog: is the maximum number of queued connections passed to :class:`~socket.socket.listen` (defaults to ``100``).
            reuse_port: tells the kernel to allow this endpoint to be bound to the same port as other existing endpoints
                        are bound to, so long as they all set this flag when being created.
                        This option is not supported on Windows.

        Raises:
            OSError: unrelated OS error occurred.

        Returns:
            A sequence of listener sockets.
        """
        raise NotImplementedError

    async def create_ssl_over_tcp_listeners(
        self,
        host: str | Sequence[str] | None,
        port: int,
        backlog: int,
        ssl_context: _typing_ssl.SSLContext,
        *,
        ssl_handshake_timeout: float,
        ssl_shutdown_timeout: float,
        reuse_port: bool = ...,
    ) -> Sequence[AsyncListenerSocketAdapter]:
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
            backlog: is the maximum number of queued connections passed to :class:`~socket.socket.listen` (defaults to ``100``).
            ssl: can be set to an :class:`ssl.SSLContext` instance to enable TLS over the accepted connections.
            ssl_handshake_timeout: (for a TLS connection) the time in seconds to wait for the TLS handshake to complete
                                   before aborting the connection. ``60.0`` seconds if :data:`None` (default).
            ssl_shutdown_timeout: the time in seconds to wait for the SSL shutdown to complete before aborting the connection.
                                  ``30.0`` seconds if :data:`None` (default).
            reuse_port: tells the kernel to allow this endpoint to be bound to the same port as other existing endpoints
                        are bound to, so long as they all set this flag when being created.
                        This option is not supported on Windows.

        Raises:
            OSError: unrelated OS error occurred.

        Returns:
            A sequence of listener sockets.
        """
        raise NotImplementedError("SSL/TLS is not supported by this backend")

    @abstractmethod
    async def create_udp_endpoint(
        self,
        *,
        local_address: tuple[str, int] | None = ...,
        remote_address: tuple[str, int] | None = ...,
        reuse_port: bool = ...,
    ) -> AsyncDatagramSocketAdapter:
        """
        Opens an endpoint using the UDP protocol.

        Parameters:
            remote_address: If given, is a ``(host, port)`` tuple used to connect the socket.
            local_address: If given, is a ``(local_host, local_port)`` tuple used to bind the socket locally.
            reuse_port: If :data:`True`, sets the :data:`~socket.SO_REUSEPORT` socket option if supported.

        Raises:
            OSError: unrelated OS error occurred.

        Returns:
            A datagram socket.
        """
        raise NotImplementedError

    @abstractmethod
    async def wrap_udp_socket(self, socket: _socket.socket) -> AsyncDatagramSocketAdapter:
        """
        Wraps an already open UDP socket into an asynchronous datagram socket.

        Important:
            The returned stream socket takes the ownership of `socket`.

            You should use :meth:`AsyncDatagramSocketAdapter.aclose` to close the socket.

        Parameters:
            socket: The socket to wrap.

        Raises:
            ValueError: Invalid socket type or family.

        Returns:
            A datagram socket.
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

        Parameters:
            lock: If given, it must be a lock created by :meth:`create_lock`. Otherwise a new Lock object is created automatically.

        Returns:
            A new Condition.
        """
        raise NotImplementedError

    @abstractmethod
    async def run_in_thread(self, func: Callable[_P, _T], /, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        """
        Executes a synchronous function in a worker thread.

        This is useful to execute a long-running (or temporarily blocking) function and let other tasks run.

        From inside the worker thread, you can get back into the scheduler loop using a :class:`ThreadsPortal`.
        See :meth:`create_threads_portal` for details.

        Cancellation handling:
            Because there is no way to "cancel" an arbitrary function call in an OS thread,
            once the job is started, any cancellation requests will be discarded.

        Warning:
            Due to the current coroutine implementation, `func` should not raise a :exc:`StopIteration`.
            This can lead to unexpected (and unwanted) behavior.

        Parameters:
            func: A synchronous function.
            args: Positional arguments to be passed to `func`.
            kwargs: Keyword arguments to be passed to `func`.

        Raises:
            Exception: Whatever ``func(*args, **kwargs)`` raises.

        Returns:
            Whatever ``func(*args, **kwargs)`` returns.
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

    @abstractmethod
    async def wait_future(self, future: concurrent.futures.Future[_T_co]) -> _T_co:
        """
        Blocks until the future is done, and returns the result.

        Cancellation handling:
            In the case of cancellation, the rules follows what :class:`concurrent.futures.Future` defines:

            * :meth:`wait_future` tries to cancel the given `future` (using :meth:`concurrent.futures.Future.cancel`)

            * If the future has been effectively cancelled, the cancellation request is "accepted" and propagated.

            * Otherwise, the cancellation request is "rejected" and discarded.
              :meth:`wait_future` will block until `future` is done, and will ignore any further cancellation request.

            * A coroutine awaiting a `future` in ``running`` state (:meth:`concurrent.futures.Future.running` returns :data:`True`)
              cannot be cancelled.

        Parameters:
            future: The :class:`~concurrent.futures.Future` object to wait for.

        Raises:
            concurrent.futures.CancelledError: the future has been unexpectedly cancelled by an external code
                                               (typically :meth:`concurrent.futures.Executor.shutdown`).
            Exception: If ``future.exception()`` does not return :data:`None`, this exception is raised.

        Returns:
            Whatever returns ``future.result()``
        """
        raise NotImplementedError
