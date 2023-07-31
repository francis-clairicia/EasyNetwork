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
from typing import TYPE_CHECKING, Self

from ...exceptions import ServerAlreadyRunning, ServerClosedError
from ...tools.lock import ForkSafeLock
from .abc import AbstractStandaloneNetworkServer

if TYPE_CHECKING:
    from ...api_async.backend.abc import AbstractRunner, AbstractThreadsPortal, IEvent
    from ...api_async.server.abc import AbstractAsyncNetworkServer


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
        self.__threads_portal: AbstractThreadsPortal | None = None
        self.__is_shutdown = _threading.Event()
        self.__is_shutdown.set()
        self.__runner: AbstractRunner | None = self.__server.get_backend().new_runner()
        self.__close_lock = ForkSafeLock()
        self.__bootstrap_lock = ForkSafeLock()

    def __enter__(self) -> Self:
        assert self.__runner is not None, "Server is entered twice"
        self.__runner.__enter__()
        return super().__enter__()

    def is_serving(self) -> bool:
        if (portal := self.__threads_portal) is not None:
            with _contextlib.suppress(RuntimeError):
                return portal.run_sync(self.__server.is_serving)
        return False

    def server_close(self) -> None:
        with self.__close_lock.get(), _contextlib.ExitStack() as stack, _contextlib.suppress(RuntimeError):
            if (portal := self.__threads_portal) is not None:
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
        if (portal := self.__threads_portal) is not None:
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
        with _contextlib.suppress(TimeoutError):
            async with backend.timeout(timeout_delay):
                await self.__server.shutdown()

    def serve_forever(self, *, is_up_event: _threading.Event | None = None) -> None:
        async def serve_forever() -> None:
            assert self.__threads_portal is None, "Server is already running"
            backend = self.__server.get_backend()
            try:
                self.__threads_portal = backend.create_threads_portal()
                is_up_event_async: IEvent | None = None
                async with backend.create_task_group() as task_group:
                    if is_up_event is not None:
                        is_up_event_async = backend.create_event()

                        async def wait_and_set_event(is_up_event_async: IEvent, is_up_event: _threading.Event) -> None:
                            await is_up_event_async.wait()
                            is_up_event.set()

                        task_group.start_soon(wait_and_set_event, is_up_event_async, is_up_event)
                        del wait_and_set_event
                    await self.__server.serve_forever(is_up_event=is_up_event_async)
            finally:
                self.__threads_portal = None
                await backend.coro_yield()  # Everyone must know about the server's death :)

        backend = self.__server.get_backend()
        with _contextlib.ExitStack() as stack, _contextlib.suppress(backend.get_cancelled_exc_class()):
            if is_up_event is not None:
                # Force is_up_event to be set, in order not to stuck the waiting thread
                stack.callback(is_up_event.set)

            with self.__close_lock.get():
                runner = self.__runner
                if runner is None:
                    raise ServerClosedError("Closed server")

            with self.__bootstrap_lock.get():
                if not self.__is_shutdown.is_set():
                    raise ServerAlreadyRunning("Server is already running")

                def safe_shutdown_set() -> None:
                    with self.__bootstrap_lock.get():
                        self.__is_shutdown.set()

                self.__is_shutdown.clear()
                stack.callback(safe_shutdown_set)

            runner.run(serve_forever)

    @property
    def _server(self) -> AbstractAsyncNetworkServer:
        return self.__server

    @property
    def _portal(self) -> AbstractThreadsPortal | None:
        return self.__threads_portal
