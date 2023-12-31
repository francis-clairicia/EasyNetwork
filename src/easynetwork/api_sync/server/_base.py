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
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any

from ...api_async.server.abc import SupportsEventSet
from ...exceptions import ServerAlreadyRunning, ServerClosedError
from ...lowlevel import _utils
from ...lowlevel._lock import ForkSafeLock
from ...lowlevel.api_async.backend.abc import ThreadsPortal
from ...lowlevel.api_async.backend.factory import AsyncBackendFactory as _Factory
from ...lowlevel.socket import SocketAddress
from .abc import AbstractNetworkServer

if TYPE_CHECKING:
    from ...api_async.server.abc import AbstractAsyncNetworkServer


class BaseStandaloneNetworkServerImpl(AbstractNetworkServer):
    __slots__ = (
        "__server_factory",
        "__default_runner_options",
        "__private_server",
        "__backend_name",
        "__close_lock",
        "__bootstrap_lock",
        "__private_threads_portal",
        "__is_shutdown",
        "__is_closed",
    )

    def __init__(
        self,
        backend: str,
        server_factory: Callable[[], AbstractAsyncNetworkServer],
        *,
        runner_options: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__()
        self.__backend_name: str = backend
        self.__server_factory: Callable[[], AbstractAsyncNetworkServer] = server_factory
        self.__private_server: AbstractAsyncNetworkServer | None = None
        self.__private_threads_portal: ThreadsPortal | None = None
        self.__is_shutdown = _threading.Event()
        self.__is_shutdown.set()
        self.__is_closed = _threading.Event()
        self.__close_lock = ForkSafeLock()
        self.__bootstrap_lock = ForkSafeLock()
        self.__default_runner_options: dict[str, Any] = dict(runner_options) if runner_options else {}

    @_utils.inherit_doc(AbstractNetworkServer)
    def is_serving(self) -> bool:
        if (portal := self._portal) is not None and (server := self._server) is not None:
            with contextlib.suppress(RuntimeError):
                return portal.run_sync(server.is_serving)
        return False

    @_utils.inherit_doc(AbstractNetworkServer)
    def server_close(self) -> None:
        with self.__close_lock.get(), contextlib.ExitStack() as stack:
            stack.callback(self.__is_closed.set)

            # Ensure we are not in the interval between the server shutdown and the scheduler shutdown
            stack.callback(self.__is_shutdown.wait)

            if (server := self._server) is not None and (portal := self._portal) is not None:
                with contextlib.suppress(RuntimeError, concurrent.futures.CancelledError):
                    portal.run_coroutine(server.server_close)

    @_utils.inherit_doc(AbstractNetworkServer)
    def shutdown(self, timeout: float | None = None) -> None:
        if (portal := self._portal) is not None and (server := self._server) is not None:
            with contextlib.suppress(RuntimeError, concurrent.futures.CancelledError), _utils.ElapsedTime() as elapsed:
                # If shutdown() have been cancelled, that means the scheduler itself is shutting down, and this is what we want
                if timeout is None:
                    portal.run_coroutine(server.shutdown)
                else:
                    portal.run_coroutine(self.__do_shutdown_with_timeout, server, timeout)
            if timeout is not None:
                timeout = elapsed.recompute_timeout(timeout)
        self.__is_shutdown.wait(timeout)

    @staticmethod
    async def __do_shutdown_with_timeout(server: AbstractAsyncNetworkServer, timeout_delay: float) -> None:
        with _Factory.current().move_on_after(timeout_delay):
            await server.shutdown()

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
            runner_options: Options to pass to the :meth:`.AsyncBackend.bootstrap` method.
                            The specified keys override the keys passed at initialization.

        Raises:
            ServerClosedError: The server is closed.
            ServerAlreadyRunning: Another task already called :meth:`serve_forever`.
        """
        if self.__default_runner_options:
            if runner_options:
                runner_options = {**self.__default_runner_options, **runner_options}
            else:
                runner_options = self.__default_runner_options.copy()

        backend = _Factory.get_backend(self.__backend_name)
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

            def reset_values() -> None:
                self.__private_threads_portal = None
                self.__private_server = None

            def acquire_bootstrap_lock() -> None:
                locks_stack.enter_context(self.__bootstrap_lock.get())

            server_exit_stack.callback(reset_values)
            server_exit_stack.callback(acquire_bootstrap_lock)

            async def serve_forever() -> None:
                async with (
                    self.__server_factory() as self.__private_server,
                    backend.create_threads_portal() as self.__private_threads_portal,
                ):
                    server = self.__private_server
                    # Initialization finished; release the locks
                    locks_stack.close()

                    await server.serve_forever(is_up_event=is_up_event)

            backend.bootstrap(serve_forever, runner_options=runner_options)

    @_utils.inherit_doc(AbstractNetworkServer)
    def get_addresses(self) -> Sequence[SocketAddress]:
        if (portal := self._portal) is not None and (server := self._server) is not None:
            with contextlib.suppress(RuntimeError):
                return portal.run_sync(server.get_addresses)
        return ()

    @property
    def _server(self) -> AbstractAsyncNetworkServer | None:
        with self.__bootstrap_lock.get():
            return self.__private_server

    @property
    def _portal(self) -> ThreadsPortal | None:
        with self.__bootstrap_lock.get():
            return self.__private_threads_portal
