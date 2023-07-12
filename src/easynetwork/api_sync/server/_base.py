# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Asynchronous network server module"""

from __future__ import annotations

__all__ = ["BaseStandaloneNetworkServerImpl"]

import contextlib as _contextlib
import threading as _threading
import time
from typing import TYPE_CHECKING

from ...exceptions import ServerAlreadyRunning
from .abc import AbstractStandaloneNetworkServer

if TYPE_CHECKING:
    from ...api_async.backend.abc import AbstractThreadsPortal, IEvent
    from ...api_async.server.abc import AbstractAsyncNetworkServer


class BaseStandaloneNetworkServerImpl(AbstractStandaloneNetworkServer):
    __slots__ = (
        "__server",
        "__threads_portal",
        "__is_shutdown",
    )

    def __init__(self, server: AbstractAsyncNetworkServer) -> None:
        super().__init__()
        self.__server: AbstractAsyncNetworkServer = server
        self.__threads_portal: AbstractThreadsPortal | None = None
        self.__is_shutdown = _threading.Event()
        self.__is_shutdown.set()

    def is_serving(self) -> bool:
        if (portal := self.__threads_portal) is not None:
            with _contextlib.suppress(RuntimeError):
                return portal.run_sync(self.__server.is_serving)
        return False

    def server_close(self) -> None:
        backend = self.__server.get_backend()
        if (portal := self.__threads_portal) is not None:
            with _contextlib.suppress(RuntimeError):
                portal.run_coroutine(lambda: backend.ignore_cancellation(self.__server.server_close()))
        else:
            self.__is_shutdown.wait()  # Ensure we are not in the interval between the server shutdown and the scheduler shutdown
            backend.bootstrap(self.__server.server_close)

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
        async def wait_and_set_event(is_up_event_async: IEvent, is_up_event: _threading.Event) -> None:
            await is_up_event_async.wait()
            is_up_event.set()

        async def serve_forever() -> None:
            if self.__threads_portal is not None:
                raise ServerAlreadyRunning("Server is already running")
            backend = self.__server.get_backend()
            try:
                self.__threads_portal = backend.create_threads_portal()
                is_up_event_async: IEvent | None = None
                async with self.__server, backend.create_task_group() as task_group:
                    if is_up_event is not None:
                        is_up_event_async = backend.create_event()
                        task_group.start_soon(wait_and_set_event, is_up_event_async, is_up_event)
                    await self.__server.serve_forever(is_up_event=is_up_event_async)
            finally:
                self.__threads_portal = None

        backend = self.__server.get_backend()
        with _contextlib.suppress(backend.get_cancelled_exc_class()), _contextlib.ExitStack() as stack:
            stack.callback(self.__is_shutdown.set)
            self.__is_shutdown.clear()

            if is_up_event is not None:
                # Force is_up_event to be set, in order not to stuck the waiting thread
                stack.callback(is_up_event.set)
            backend.bootstrap(serve_forever)

    @property
    def _server(self) -> AbstractAsyncNetworkServer:
        return self.__server

    @property
    def _portal(self) -> AbstractThreadsPortal | None:
        return self.__threads_portal
