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
import contextlib
import threading as _threading
import time
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, NoReturn

from ...api_async.server.abc import SupportsEventSet
from ...exceptions import ServerAlreadyRunning, ServerClosedError
from ...lowlevel._lock import ForkSafeLock
from ...lowlevel.api_async.backend.abc import ThreadsPortal
from ...lowlevel.socket import SocketAddress
from .abc import AbstractNetworkServer

if TYPE_CHECKING:
    from ...api_async.server.abc import AbstractAsyncNetworkServer


class BaseStandaloneNetworkServerImpl(AbstractNetworkServer):
    __slots__ = (
        "__server",
        "__close_lock",
        "__bootstrap_lock",
        "__threads_portal",
        "__is_shutdown",
        "__is_closed",
    )

    def __init__(self, server: AbstractAsyncNetworkServer) -> None:
        super().__init__()
        self.__server: AbstractAsyncNetworkServer = server
        self.__threads_portal: ThreadsPortal | None = None
        self.__is_shutdown = _threading.Event()
        self.__is_shutdown.set()
        self.__is_closed = _threading.Event()
        self.__close_lock = ForkSafeLock()
        self.__bootstrap_lock = ForkSafeLock()

    def is_serving(self) -> bool:
        if (portal := self._portal) is not None:
            with contextlib.suppress(RuntimeError):
                return portal.run_sync(self.__server.is_serving)
        return False

    is_serving.__doc__ = AbstractNetworkServer.is_serving.__doc__

    def server_close(self) -> None:
        with self.__close_lock.get(), contextlib.ExitStack() as stack, contextlib.suppress(RuntimeError):
            if (portal := self._portal) is not None:
                with contextlib.suppress(concurrent.futures.CancelledError):
                    portal.run_coroutine(self.__server.server_close)
            else:
                stack.callback(self.__is_closed.set)
                self.__is_shutdown.wait()  # Ensure we are not in the interval between the server shutdown and the scheduler shutdown
                backend = self.__server.get_backend()
                backend.bootstrap(self.__server.server_close)

    server_close.__doc__ = AbstractNetworkServer.server_close.__doc__

    def shutdown(self, timeout: float | None = None) -> None:
        if (portal := self._portal) is not None:
            with contextlib.suppress(RuntimeError, concurrent.futures.CancelledError):
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

    shutdown.__doc__ = AbstractNetworkServer.shutdown.__doc__

    async def __do_shutdown_with_timeout(self, timeout_delay: float) -> None:
        backend = self.__server.get_backend()
        with backend.move_on_after(timeout_delay):
            await self.__server.shutdown()

    def serve_forever(
        self,
        *,
        is_up_event: SupportsEventSet | None = None,
        runner_options: Mapping[str, Any] | None = None,
    ) -> None:
        """
        Starts the server's main loop.

        Parameters:
            is_up_event: If given, will be triggered when the server is ready to accept new clients.
            runner_options: Options to pass to the :meth:`~AsyncBackend.bootstrap` method.

        Raises:
            ServerClosedError: The server is closed.
            ServerAlreadyRunning: Another task already called :meth:`serve_forever`.
        """

        backend = self.__server.get_backend()
        with contextlib.ExitStack() as server_exit_stack, contextlib.suppress(backend.get_cancelled_exc_class()):
            # locks_stack is used to acquire locks until
            # serve_forever() coroutine creates the thread portal
            locks_stack = server_exit_stack.enter_context(contextlib.ExitStack())
            locks_stack.enter_context(self.__close_lock.get())
            locks_stack.enter_context(self.__bootstrap_lock.get())

            if self.__is_closed.is_set():
                raise ServerClosedError("Closed server")

            if not self.__is_shutdown.is_set():
                raise ServerAlreadyRunning("Server is already running")

            self.__is_shutdown.clear()
            server_exit_stack.callback(self.__is_shutdown.set)

            def reset_threads_portal() -> None:
                self.__threads_portal = None

            def acquire_bootstrap_lock() -> None:
                locks_stack.enter_context(self.__bootstrap_lock.get())

            server_exit_stack.callback(reset_threads_portal)
            server_exit_stack.callback(acquire_bootstrap_lock)

            async def serve_forever() -> NoReturn:
                async with backend.create_threads_portal() as self.__threads_portal:
                    # Initialization finished; release the locks
                    locks_stack.close()

                    await self.__server.serve_forever(is_up_event=is_up_event)

            backend.bootstrap(serve_forever, runner_options=runner_options)

    def get_addresses(self) -> Sequence[SocketAddress]:
        """
        Returns all interfaces to which the listeners are bound. Thread-safe.

        Returns:
            A sequence of network socket address.
            If the server is not serving (:meth:`is_serving` returns :data:`False`), an empty sequence is returned.
        """
        if (portal := self._portal) is not None:
            with contextlib.suppress(RuntimeError):
                return portal.run_sync(self.__server.get_addresses)
        return ()

    get_addresses.__doc__ = AbstractNetworkServer.get_addresses.__doc__

    @property
    def _server(self) -> AbstractAsyncNetworkServer:
        return self.__server

    @property
    def _portal(self) -> ThreadsPortal | None:
        with self.__bootstrap_lock.get():
            return self.__threads_portal
