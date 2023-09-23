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

import concurrent.futures
import contextlib as _contextlib
import threading as _threading
import time
from typing import TYPE_CHECKING, Self

from ...api_async.backend.abc import ThreadsPortal
from ...api_async.server.abc import SupportsEventSet
from ...exceptions import ServerAlreadyRunning, ServerClosedError
from ...tools._lock import ForkSafeLock
from .abc import AbstractNetworkServer

if TYPE_CHECKING:
    from ...api_async.backend.abc import Runner
    from ...api_async.server.abc import AbstractAsyncNetworkServer


class BaseStandaloneNetworkServerImpl(AbstractNetworkServer):
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
        self.__threads_portal: ThreadsPortal | None = None
        self.__is_shutdown = _threading.Event()
        self.__is_shutdown.set()
        self.__runner: Runner | None = self.__server.get_backend().new_runner()
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

    is_serving.__doc__ = AbstractNetworkServer.is_serving.__doc__

    def server_close(self) -> None:
        with self.__close_lock.get(), _contextlib.ExitStack() as stack, _contextlib.suppress(RuntimeError):
            if (portal := self._portal) is not None:
                with _contextlib.suppress(concurrent.futures.CancelledError):
                    portal.run_coroutine(self.__server.server_close)
            else:
                runner, self.__runner = self.__runner, None
                if runner is None:
                    return
                stack.push(runner)
                self.__is_shutdown.wait()  # Ensure we are not in the interval between the server shutdown and the scheduler shutdown
                runner.run(self.__server.server_close)

    server_close.__doc__ = AbstractNetworkServer.server_close.__doc__

    def shutdown(self, timeout: float | None = None) -> None:
        if (portal := self._portal) is not None:
            try:
                # If shutdown() have been cancelled, that means the scheduler itself is shutting down, and this is what we want
                if timeout is None:
                    portal.run_coroutine(self.__server.shutdown)
                else:
                    _start = time.perf_counter()
                    try:
                        portal.run_coroutine(self.__do_shutdown_with_timeout, timeout)
                    finally:
                        timeout -= time.perf_counter() - _start
            except (RuntimeError, concurrent.futures.CancelledError):
                pass
        self.__is_shutdown.wait(timeout)

    shutdown.__doc__ = AbstractNetworkServer.shutdown.__doc__

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

            async def serve_forever() -> None:
                def reset_threads_portal() -> None:
                    self.__threads_portal = None

                def acquire_bootstrap_lock() -> None:
                    locks_stack.enter_context(self.__bootstrap_lock.get())

                server_exit_stack.callback(reset_threads_portal)
                server_exit_stack.callback(acquire_bootstrap_lock)

                async with backend.create_threads_portal() as self.__threads_portal:
                    # Initialization finished; release the locks
                    locks_stack.close()

                    await self.__server.serve_forever(is_up_event=is_up_event)

            runner.run(serve_forever)

    serve_forever.__doc__ = AbstractNetworkServer.serve_forever.__doc__

    @property
    def _server(self) -> AbstractAsyncNetworkServer:
        return self.__server

    @property
    def _portal(self) -> ThreadsPortal | None:
        with self.__bootstrap_lock.get():
            return self.__threads_portal
