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
"""Asynchronous network server module"""

from __future__ import annotations

__all__ = ["BaseStandaloneNetworkServerImpl"]

import contextlib as _contextlib
import threading as _threading
import time
from collections.abc import Callable, Coroutine, Iterator
from typing import TYPE_CHECKING, Any, ParamSpec, Self, TypeVar, final

from ...api_async.backend.abc import AbstractThreadsPortal
from ...api_async.server.abc import SupportsEventSet
from ...exceptions import ServerAlreadyRunning, ServerClosedError
from ...tools._lock import ForkSafeLock
from .abc import AbstractStandaloneNetworkServer

if TYPE_CHECKING:
    from ...api_async.backend.abc import AbstractAsyncBackend, AbstractRunner
    from ...api_async.server.abc import AbstractAsyncNetworkServer


_P = ParamSpec("_P")
_T = TypeVar("_T")


class BaseStandaloneNetworkServerImpl(AbstractStandaloneNetworkServer):
    __slots__ = (
        "__server",
        "__runner",
        "__close_lock",
        "__bootstrap_lock",
        "__threads_portal",
        "__is_shutdown",
    )

    def __init__(self, server: AbstractAsyncNetworkServer) -> None:
        super().__init__()
        self.__server: AbstractAsyncNetworkServer = server
        self.__threads_portal: _ServerThreadsPortal | None = None
        self.__is_shutdown = _threading.Event()
        self.__is_shutdown.set()
        self.__runner: AbstractRunner | None = self.__server.get_backend().new_runner()
        self.__close_lock = ForkSafeLock()
        self.__bootstrap_lock = ForkSafeLock()

    def __enter__(self) -> Self:
        assert self.__runner is not None, "Server is entered twice"  # nosec assert_used
        self.__runner.__enter__()
        return super().__enter__()

    def is_serving(self) -> bool:
        if (portal := self._portal) is not None:
            with _contextlib.suppress(RuntimeError):
                return portal.run_sync(self.__server.is_serving)
        return False

    def server_close(self) -> None:
        with self.__close_lock.get(), _contextlib.ExitStack() as stack, _contextlib.suppress(RuntimeError):
            if (portal := self._portal) is not None:
                CancelledError = self.__server.get_backend().get_cancelled_exc_class()
                with _contextlib.suppress(CancelledError):
                    portal.run_coroutine(self.__server.server_close)
            else:
                runner, self.__runner = self.__runner, None
                if runner is None:
                    return
                stack.push(runner)
                self.__is_shutdown.wait()  # Ensure we are not in the interval between the server shutdown and the scheduler shutdown
                runner.run(self.__server.server_close)

    def shutdown(self, timeout: float | None = None) -> None:
        if (portal := self._portal) is not None:
            CancelledError = self.__server.get_backend().get_cancelled_exc_class()
            with _contextlib.suppress(RuntimeError, CancelledError):
                # If shutdown() have been cancelled, that means the scheduler itself is shutting down, and this is what we want
                if timeout is None:
                    portal.run_coroutine(self.__server.shutdown)
                else:
                    _start = time.perf_counter()
                    try:
                        portal.run_coroutine(self.__do_shutdown_with_timeout, timeout)
                    finally:
                        timeout -= time.perf_counter() - _start
        self.__is_shutdown.wait(timeout)

    async def __do_shutdown_with_timeout(self, timeout_delay: float) -> None:
        backend = self.__server.get_backend()
        async with backend.move_on_after(timeout_delay):
            await self.__server.shutdown()

    def serve_forever(self, *, is_up_event: SupportsEventSet | None = None) -> None:
        backend = self.__server.get_backend()
        with _contextlib.ExitStack() as server_exit_stack, _contextlib.suppress(backend.get_cancelled_exc_class()):
            if is_up_event is not None:
                # Force is_up_event to be set, in order not to stuck the waiting thread
                server_exit_stack.callback(is_up_event.set)

            # locks_stack is used to acquire locks until
            # serve_forever() coroutine creates the thread portal
            locks_stack = server_exit_stack.enter_context(_contextlib.ExitStack())
            locks_stack.enter_context(self.__close_lock.get())
            locks_stack.enter_context(self.__bootstrap_lock.get())

            runner = self.__runner
            if runner is None:
                raise ServerClosedError("Closed server")

            if not self.__is_shutdown.is_set():
                raise ServerAlreadyRunning("Server is already running")

            self.__is_shutdown.clear()
            server_exit_stack.callback(self.__is_shutdown.set)

            async def serve_forever(runner: AbstractRunner) -> None:
                try:
                    self.__threads_portal = _ServerThreadsPortal(backend, runner)
                    server_exit_stack.callback(self.__threads_portal._wait_for_all_requests)

                    # Initialization finished; release the locks
                    locks_stack.close()

                    await self.__server.serve_forever(is_up_event=is_up_event)
                finally:
                    self.__threads_portal = None

            try:
                runner.run(serve_forever, runner)
            finally:
                # Acquire the bootstrap lock at teardown, before calling is_shutdown.set().
                locks_stack.enter_context(self.__bootstrap_lock.get())

    @property
    def _server(self) -> AbstractAsyncNetworkServer:
        return self.__server

    @property
    def _portal(self) -> AbstractThreadsPortal | None:
        with self.__bootstrap_lock.get():
            return self.__threads_portal


@final
class _ServerThreadsPortal(AbstractThreadsPortal):
    __slots__ = ("__backend", "__runner", "__portal", "__request_count", "__request_count_lock")

    def __init__(self, backend: AbstractAsyncBackend, runner: AbstractRunner) -> None:
        super().__init__()
        self.__backend: AbstractAsyncBackend = backend
        self.__runner: AbstractRunner = runner
        self.__portal: AbstractThreadsPortal = backend.create_threads_portal()
        self.__request_count: int = 0
        self.__request_count_lock = ForkSafeLock()

    def run_coroutine(self, coro_func: Callable[_P, Coroutine[Any, Any, _T]], /, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        with self.__request_context():
            return self.__portal.run_coroutine(coro_func, *args, **kwargs)

    def run_sync(self, func: Callable[_P, _T], /, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        with self.__request_context():
            return self.__portal.run_sync(func, *args, **kwargs)

    def _wait_for_all_requests(self) -> None:
        while self.__request_count > 0:
            self.__runner.run(self.__backend.coro_yield)

    @_contextlib.contextmanager
    def __request_context(self) -> Iterator[None]:
        request_count_lock = self.__request_count_lock
        with request_count_lock.get():
            self.__request_count += 1
        try:
            yield
        finally:
            with request_count_lock.get():
                self.__request_count -= 1
