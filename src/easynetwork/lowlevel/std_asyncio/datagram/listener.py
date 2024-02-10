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
"""asyncio engine for easynetwork.async
"""

from __future__ import annotations

__all__ = ["DatagramListenerSocketAdapter"]

import asyncio
import collections
import contextlib
import dataclasses
import errno as _errno
import logging
from collections.abc import Callable, Coroutine, Mapping
from typing import TYPE_CHECKING, Any, NoReturn, final

from ... import _utils, socket as socket_tools
from ...api_async.transports import abc as transports
from ..tasks import TaskGroup as AsyncIOTaskGroup
from .endpoint import _monkeypatch_transport

if TYPE_CHECKING:
    import asyncio.trsock

    from ...api_async.backend.abc import TaskGroup as AbstractTaskGroup


@final
class DatagramListenerSocketAdapter(transports.AsyncDatagramListener[tuple[Any, ...]]):
    __slots__ = (
        "__transport",
        "__protocol",
        "__socket",
        "__closing",
    )

    def __init__(self, transport: asyncio.DatagramTransport, protocol: DatagramListenerProtocol) -> None:
        super().__init__()

        self.__transport: asyncio.DatagramTransport = transport
        self.__protocol: DatagramListenerProtocol = protocol

        socket: asyncio.trsock.TransportSocket | None = transport.get_extra_info("socket")
        assert socket is not None, "transport must be a socket transport"  # nosec assert_used

        self.__socket: asyncio.trsock.TransportSocket = socket
        # asyncio.DatagramTransport.is_closing() can suddently become true if there is something wrong with the socket
        # even if transport.close() was never called.
        # To bypass this side effect, we use our own flag.
        self.__closing: bool = False

    def is_closing(self) -> bool:
        return self.__closing

    async def aclose(self) -> None:
        self.__closing = True
        if not self.__transport.is_closing():
            self.__transport.close()
        await asyncio.shield(self.__protocol._get_close_waiter())

    async def serve(
        self,
        handler: Callable[[bytes, tuple[Any, ...]], Coroutine[Any, Any, None]],
        task_group: AbstractTaskGroup | None = None,
    ) -> NoReturn:
        async with contextlib.AsyncExitStack() as stack:
            if task_group is None:
                task_group = await stack.enter_async_context(AsyncIOTaskGroup())
            await self.__protocol.serve(handler, task_group)

        raise AssertionError("Expected code to be unreachable.")

    async def send_to(self, data: bytes | bytearray | memoryview, address: tuple[Any, ...]) -> None:
        assert address is not None, "Address is None"  # nosec assert_used
        self.__transport.sendto(data, address)
        await self.__protocol.writer_drain()

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        socket = self.__socket
        return socket_tools._get_socket_extra(socket, wrap_in_proxy=False)


@dataclasses.dataclass(eq=False, frozen=True, slots=True)
class _DatagramListenerServeContext:
    datagram_handler: Callable[[bytes, tuple[Any, ...]], Coroutine[Any, Any, None]]
    task_group: AbstractTaskGroup
    __queue: collections.deque[tuple[bytes, tuple[Any, ...]]] = dataclasses.field(init=False, default_factory=collections.deque)

    def handle(self, data: bytes, addr: tuple[Any, ...]) -> None:
        self.__queue.append((data, addr))
        self.task_group.start_soon(self.__datagram_handler_task)

    async def __datagram_handler_task(self) -> None:
        data, addr = self.__queue.popleft()
        await self.datagram_handler(data, addr)


class DatagramListenerProtocol(asyncio.DatagramProtocol):
    __slots__ = (
        "__loop",
        "__datagram_serve_ctx",
        "__delayed_datagrams_queue",
        "__transport",
        "__closed",
        "__drain_waiters",
        "__write_paused",
        "__connection_lost",
        "__connection_lost_exception",
        "__serve_forever_fut",
    )

    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        super().__init__()
        if loop is None:
            loop = asyncio.get_running_loop()
        self.__loop: asyncio.AbstractEventLoop = loop
        self.__datagram_serve_ctx: _DatagramListenerServeContext | None = None
        self.__delayed_datagrams_queue: collections.deque[tuple[bytes, tuple[Any, ...]]] = collections.deque()
        self.__transport: asyncio.DatagramTransport | None = None
        self.__closed: asyncio.Future[None] = loop.create_future()
        self.__drain_waiters: collections.deque[asyncio.Future[None]] = collections.deque()
        self.__write_paused: bool = False
        self.__connection_lost: bool = False
        self.__connection_lost_exception: Exception | None = None
        self.__serve_forever_fut: asyncio.Future[NoReturn] = loop.create_future()

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:  # type: ignore[override]
        assert self.__transport is None, "Transport already set"  # nosec assert_used
        self.__transport = transport
        self.__connection_lost = False
        _monkeypatch_transport(transport, self.__loop)

    def connection_lost(self, exc: Exception | None) -> None:
        self.__connection_lost = True
        self.__connection_lost_exception = exc
        self.__serve_forever_fut.cancel(msg="connection_lost()")

        if not self.__closed.done():
            self.__closed.set_result(None)

        self._wakeup_write_waiters(exc)

        self.__transport = None

    def datagram_received(self, data: bytes, addr: tuple[Any, ...]) -> None:
        if (datagram_serve_ctx := self.__datagram_serve_ctx) is None:
            # serve() is not yet awaited.
            self.__delayed_datagrams_queue.append((data, addr))
        else:
            datagram_serve_ctx.handle(data, addr)

    def error_received(self, exc: Exception) -> None:
        if not self.__connection_lost:
            logger = logging.getLogger(__name__)
            message = "Unrelated error occurred on datagram reception: %s: %s"
            logger.warning(message, type(exc).__name__, exc, exc_info=exc if self.__loop.get_debug() else None)

    async def serve(
        self,
        handler: Callable[[bytes, tuple[Any, ...]], Coroutine[Any, Any, None]],
        task_group: AbstractTaskGroup,
    ) -> NoReturn:
        if self.__datagram_serve_ctx is not None:
            raise RuntimeError("DatagramListenerProtocol.serve() awaited twice")

        self.__datagram_serve_ctx = _DatagramListenerServeContext(handler, task_group)
        try:
            # First, dequeue datagrams received during setup.
            while self.__delayed_datagrams_queue:
                self.__datagram_serve_ctx.handle(*self.__delayed_datagrams_queue.popleft())

            # Wait until either connection_lost() or cancellation
            await asyncio.shield(self.__serve_forever_fut)
        finally:
            self.__datagram_serve_ctx = None

    def pause_writing(self) -> None:
        self.__write_paused = True

    def resume_writing(self) -> None:
        self.__write_paused = False

        self._wakeup_write_waiters(None)

    async def writer_drain(self) -> None:
        if self.__connection_lost:
            if self.__connection_lost_exception is not None:
                raise self.__connection_lost_exception
            raise _utils.error_from_errno(_errno.ECONNABORTED)
        if not self.__write_paused:
            return
        waiter = self.__loop.create_future()
        self.__drain_waiters.append(waiter)
        try:
            await waiter
        finally:
            self.__drain_waiters.remove(waiter)
            del waiter

    def _wakeup_write_waiters(self, exc: Exception | None) -> None:
        for waiter in self.__drain_waiters:
            if not waiter.done():
                if exc is None:
                    waiter.set_result(None)
                else:
                    waiter.set_exception(exc)

    def _get_close_waiter(self) -> asyncio.Future[None]:
        return self.__closed

    def _get_loop(self) -> asyncio.AbstractEventLoop:
        return self.__loop

    def _writing_paused(self) -> bool:
        return self.__write_paused
