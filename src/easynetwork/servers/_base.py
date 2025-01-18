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
"""Generic network servers module."""

from __future__ import annotations

__all__ = ["BaseAsyncNetworkServerImpl", "BaseStandaloneNetworkServerImpl"]

import concurrent.futures
import contextlib
import dataclasses
import logging
import threading as _threading
from abc import abstractmethod
from collections.abc import Awaitable, Callable, Mapping, Sequence
from types import TracebackType
from typing import Any, Generic, NoReturn, Protocol, Self, TypeVar

from ..exceptions import ServerAlreadyRunning, ServerClosedError
from ..lowlevel import _utils
from ..lowlevel._lock import ForkSafeLock
from ..lowlevel.api_async.backend.abc import AsyncBackend, CancelScope, Task, TaskGroup, ThreadsPortal
from ..lowlevel.api_async.backend.utils import BuiltinAsyncBackendLiteral, ensure_backend
from .abc import AbstractAsyncNetworkServer, AbstractNetworkServer, SupportsEventSet


class _SupportsAclose(Protocol):
    @abstractmethod
    def is_closing(self) -> bool: ...
    @abstractmethod
    def aclose(self) -> Awaitable[object]: ...


_T_Address = TypeVar("_T_Address")
_T_Return = TypeVar("_T_Return")
_T_Default = TypeVar("_T_Default")
_T_AsyncServer = TypeVar("_T_AsyncServer", bound=AbstractAsyncNetworkServer)


##############################################################################################################
#
# BLOCKING SERVER
#
##############################################################################################################


class BaseStandaloneNetworkServerImpl(AbstractNetworkServer, Generic[_T_AsyncServer]):
    __slots__ = (
        "__server_factory",
        "__default_runner_options",
        "__server",
        "__backend",
        "__close_lock",
        "__bootstrap_lock",
        "__threads_portal",
        "__is_shutdown",
        "__is_closed",
    )

    def __init__(
        self,
        backend: AsyncBackend | BuiltinAsyncBackendLiteral | None,
        server_factory: Callable[[AsyncBackend], _T_AsyncServer],
        *,
        runner_options: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__()

        backend = ensure_backend("asyncio" if backend is None else backend)

        self.__backend: AsyncBackend = backend
        self.__server_factory: Callable[[AsyncBackend], _T_AsyncServer] = server_factory
        self.__server: _T_AsyncServer | None = None
        self.__threads_portal: ThreadsPortal | None = None
        self.__is_shutdown = _threading.Event()
        self.__is_shutdown.set()
        self.__is_closed = _threading.Event()
        self.__close_lock = ForkSafeLock()
        self.__bootstrap_lock = ForkSafeLock()
        self.__default_runner_options: dict[str, Any] = dict(runner_options) if runner_options else {}

    def _run_sync_or_else(
        self,
        f: Callable[[ThreadsPortal, _T_AsyncServer], _T_Return],
        default: Callable[[], _T_Default],
    ) -> _T_Return | _T_Default:
        with self.__bootstrap_lock.get():
            if (portal := self.__threads_portal) is not None and (server := self.__server) is not None:
                with contextlib.suppress(RuntimeError, concurrent.futures.CancelledError):
                    return f(portal, server)
        return default()

    def _run_sync_or(
        self,
        f: Callable[[ThreadsPortal, _T_AsyncServer], _T_Return],
        default: _T_Default,
    ) -> _T_Return | _T_Default:
        return self._run_sync_or_else(f, lambda: default)

    @_utils.inherit_doc(AbstractNetworkServer)
    def is_serving(self) -> bool:
        return self._run_sync_or(lambda portal, server: portal.run_sync(server.is_serving), False)

    @_utils.inherit_doc(AbstractNetworkServer)
    def server_close(self) -> None:
        with self.__close_lock.get(), contextlib.ExitStack() as stack:
            stack.callback(self.__is_closed.set)
            self._run_sync_or(lambda portal, server: portal.run_coroutine(server.server_close), None)

    @_utils.inherit_doc(AbstractNetworkServer)
    def shutdown(self, timeout: float | None = None) -> None:
        with self.__bootstrap_lock.get():
            if (portal := self.__threads_portal) is not None and (server := self.__server) is not None:

                async def do_shutdown_with_timeout(server: AbstractAsyncNetworkServer, timeout: float) -> None:
                    with server.backend().move_on_after(timeout):
                        await server.shutdown()

                with contextlib.suppress(RuntimeError, concurrent.futures.CancelledError), _utils.ElapsedTime() as elapsed:
                    # If shutdown() have been cancelled, that means the scheduler itself is shutting down,
                    # and this is what we want
                    if timeout is None:
                        portal.run_coroutine(server.shutdown)
                    else:
                        portal.run_coroutine(do_shutdown_with_timeout, server, timeout)

                if timeout is not None:
                    timeout = elapsed.recompute_timeout(timeout)
        self.__is_shutdown.wait(timeout)

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

        backend = self.__backend
        with contextlib.ExitStack() as server_exit_stack, contextlib.suppress(backend.get_cancelled_exc_class()):
            # locks_stack is used to acquire locks until
            # serve_forever() coroutine creates the thread portal
            locks_stack = server_exit_stack.enter_context(contextlib.ExitStack())

            locks_stack.enter_context(self.__close_lock.get())
            if self.__is_closed.is_set():
                raise ServerClosedError("Closed server")

            locks_stack.enter_context(self.__bootstrap_lock.get())
            if not self.__is_shutdown.is_set():
                raise ServerAlreadyRunning("Server is already running")

            self.__is_shutdown.clear()
            server_exit_stack.callback(self.__is_shutdown.set)

            def reset_values() -> None:
                self.__threads_portal = None
                self.__server = None

            def reacquire_bootstrap_lock_on_shutdown() -> None:
                locks_stack.enter_context(self.__bootstrap_lock.get())

            server_exit_stack.callback(reset_values)
            server_exit_stack.callback(reacquire_bootstrap_lock_on_shutdown)

            async def serve_forever() -> None:
                async with (
                    self.__server_factory(backend) as self.__server,
                    backend.create_threads_portal() as self.__threads_portal,
                ):
                    # Initialization finished; release the locks
                    locks_stack.close()

                    await self.__server.serve_forever(is_up_event=is_up_event)

            backend.bootstrap(serve_forever, runner_options=runner_options)


_T_LowLevelServer = TypeVar("_T_LowLevelServer", bound=_SupportsAclose)


##############################################################################################################
#
# ASYNCHRONOUS SERVER
#
##############################################################################################################


@dataclasses.dataclass(repr=False, eq=False, frozen=True, slots=True)
class _BindServer(contextlib.AbstractContextManager[None]):
    attach: Callable[[], None]
    detach: Callable[[], None]

    def __enter__(self) -> None:
        self.attach()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.detach()


class BaseAsyncNetworkServerImpl(AbstractAsyncNetworkServer, Generic[_T_LowLevelServer, _T_Address]):
    """
    An asynchronous network server for TCP connections.
    """

    __slots__ = (
        "__backend",
        "__servers",
        "__servers_factory_cb",
        "__servers_factory_scope",
        "__initialize_service_cb",
        "__lowlevel_serve_cb",
        "__server_activation_lock",
        "__server_close_lock",
        "__server_close_guard",
        "__is_shutdown",
        "__server_tasks",
        "__server_run_scope",
        "__active_tasks",
        "__logger",
    )

    def __init__(
        self,
        *,
        backend: AsyncBackend | BuiltinAsyncBackendLiteral | None,
        servers_factory: Callable[[Self], Awaitable[Sequence[_T_LowLevelServer]]],
        initialize_service: Callable[[Self, contextlib.AsyncExitStack], Awaitable[None]],
        lowlevel_serve: Callable[[Self, _T_LowLevelServer, TaskGroup], Awaitable[NoReturn]],
        logger: logging.Logger,
    ) -> None:
        """
        Parameters:
            backend: The :term:`asynchronous backend interface` to use.
        """
        super().__init__()

        backend = ensure_backend(backend)

        self.__backend: AsyncBackend = backend
        self.__servers_factory_cb: Callable[[Self], Awaitable[Sequence[_T_LowLevelServer]]] | None = servers_factory
        self.__initialize_service_cb: Callable[[Self, contextlib.AsyncExitStack], Awaitable[None]] = initialize_service
        self.__lowlevel_serve_cb: Callable[[Self, _T_LowLevelServer, TaskGroup], Awaitable[NoReturn]] = lowlevel_serve

        self.__servers_factory_scope: CancelScope | None = None
        self.__server_run_scope: CancelScope | None = None
        self.__server_activation_lock = backend.create_lock()
        self.__server_close_lock = backend.create_lock()
        self.__server_close_guard = _utils.ResourceGuard("Cannot close server during serve_forever() setup.")

        self.__servers: list[_T_LowLevelServer] = []
        self.__is_shutdown = backend.create_event()
        self.__is_shutdown.set()
        self.__server_tasks: list[Task[NoReturn]] = []
        self.__logger: logging.Logger = logger
        self.__active_tasks: int = 0

    @_utils.inherit_doc(AbstractAsyncNetworkServer)
    def is_serving(self) -> bool:
        return bool(self.__server_tasks) and all(not t.done() for t in self.__server_tasks) and self.is_listening()

    @_utils.inherit_doc(AbstractAsyncNetworkServer)
    def is_listening(self) -> bool:
        return bool(self.__servers) and all(not server.is_closing() for server in self.__servers)

    @_utils.inherit_doc(AbstractAsyncNetworkServer)
    async def server_activate(self) -> None:
        async with self.__server_activation_lock:
            assert self.__servers_factory_scope is None  # nosec assert_used
            if (servers_factory := self.__servers_factory_cb) is None:
                raise ServerClosedError("Closed server")
            if self.__servers:
                return
            listeners: list[_T_LowLevelServer] = []
            try:
                with self.__backend.open_cancel_scope() as self.__servers_factory_scope:
                    await self.__backend.coro_yield()
                    listeners.extend(await servers_factory(self))  # type: ignore[arg-type]
                if self.__servers_factory_scope.cancelled_caught():
                    raise ServerClosedError("Server has been closed")
            finally:
                self.__servers_factory_scope = None
            if not listeners:
                raise OSError("empty listeners list")
            self.__servers[:] = listeners

    @_utils.inherit_doc(AbstractAsyncNetworkServer)
    async def server_close(self) -> None:
        async with contextlib.AsyncExitStack() as exit_stack:
            await exit_stack.enter_async_context(self.__server_close_lock)
            exit_stack.enter_context(self.__server_close_guard)

            if self.__servers_factory_scope is not None:
                self.__servers_factory_scope.cancel()
            self.__servers_factory_cb = None

            exit_stack.callback(self.__servers.clear)
            exit_stack.push_async_callback(self.__close_all_servers, self.__backend, self.__servers[:])

            async with self.__backend.create_task_group() as group:
                for task in self.__server_tasks:
                    task.cancel()
                    group.start_soon(task.wait)

    @classmethod
    async def __close_all_servers(cls, backend: AsyncBackend, servers: Sequence[_T_LowLevelServer]) -> None:
        async with backend.create_task_group() as group:
            for server in servers:
                group.start_soon(cls.__close_server, server)

    @classmethod
    async def __close_server(cls, server: _T_LowLevelServer) -> None:
        await server.aclose()

    @_utils.inherit_doc(AbstractAsyncNetworkServer)
    async def shutdown(self) -> None:
        if self.__server_run_scope is not None:
            self.__server_run_scope.cancel()
        await self.__is_shutdown.wait()

    @_utils.inherit_doc(AbstractAsyncNetworkServer)
    async def serve_forever(self, *, is_up_event: SupportsEventSet | None = None) -> None:
        async with contextlib.AsyncExitStack() as server_exit_stack:
            # Wake up server
            if not self.__is_shutdown.is_set():
                raise ServerAlreadyRunning("Server is already running")
            self.__is_shutdown = is_shutdown = self.__backend.create_event()
            server_exit_stack.callback(is_shutdown.set)
            self.__server_run_scope = server_exit_stack.enter_context(self.__backend.open_cancel_scope())

            def reset_scope() -> None:
                self.__server_run_scope = None

            server_exit_stack.callback(reset_scope)
            ################

            # Bind and activate
            await self.server_activate()
            assert len(self.__servers) > 0  # nosec assert_used
            ###################

            with self.__server_close_guard:

                # Final teardown
                server_exit_stack.callback(self.__logger.info, "Server stopped")
                ################

                # Initialize service
                initialize_service = self.__initialize_service_cb
                await initialize_service(self, server_exit_stack)  # type: ignore[arg-type]
                ############################

                # Setup task group
                self.__active_tasks = 0
                server_exit_stack.callback(self.__server_tasks.clear)
                task_group = await server_exit_stack.enter_async_context(self.__backend.create_task_group())
                server_exit_stack.callback(self.__logger.info, "Server loop break, waiting for remaining tasks...")
                ##################

                # Enable listener
                self.__server_tasks[:] = [await task_group.start(self.__serve, server, task_group) for server in self.__servers]
                self.__logger.info("Start serving at %s", ", ".join(map(str, self.get_addresses())))
                #################

            # Server is up
            if is_up_event is not None:
                is_up_event.set()
            ##############

            # Main loop
            try:
                await self.__backend.sleep_forever()
            finally:
                reset_scope()

    @abstractmethod
    def get_addresses(self) -> Sequence[_T_Address]:
        """
        Returns all interfaces to which the server is bound.

        Returns:
            A sequence of network socket address.
            If the server is not serving (:meth:`is_serving` returns :data:`False`), an empty sequence is returned.
        """
        raise NotImplementedError

    def _bind_server(self) -> _BindServer:
        return _BindServer(self.__attach_server, self.__detach_server)

    async def __serve(
        self,
        server: _T_LowLevelServer,
        task_group: TaskGroup,
    ) -> NoReturn:
        lowlevel_serve = self.__lowlevel_serve_cb
        with _BindServer(self.__attach_server, self.__detach_server):
            await lowlevel_serve(self, server, task_group)  # type: ignore[arg-type]

    def __attach_server(self) -> None:
        self.__active_tasks += 1

    def __detach_server(self) -> None:
        self.__active_tasks -= 1
        if self.__active_tasks < 0:
            raise AssertionError("self.__active_tasks < 0")
        if not self.__active_tasks and self.__server_run_scope is not None:
            self.__server_run_scope.cancel()

    def _with_lowlevel_servers(self, f: Callable[[Sequence[_T_LowLevelServer]], _T_Return]) -> _T_Return:
        servers = tuple(self.__servers)
        return f(servers)

    @_utils.inherit_doc(AbstractAsyncNetworkServer)
    def backend(self) -> AsyncBackend:
        return self.__backend

    @property
    def logger(self) -> logging.Logger:
        return self.__logger
