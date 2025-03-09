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
"""asyncio engine for easynetwork.async"""

from __future__ import annotations

__all__ = ["DatagramListenerSocketAdapter"]

import asyncio
import asyncio.trsock
import collections
import contextlib
import dataclasses
import logging
import warnings
from collections.abc import Callable, Coroutine, Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, NoReturn, final

from ..... import _utils, socket as socket_tools
from ....transports import abc as transports
from ...abc import AsyncBackend, TaskGroup
from .._flow_control import WriteFlowControl
from .endpoint import _monkeypatch_transport

if TYPE_CHECKING:
    from socket import _Address, _RetAddress


@final
class DatagramListenerSocketAdapter(transports.AsyncDatagramListener["_RetAddress"]):
    __slots__ = (
        "__backend",
        "__transport",
        "__protocol",
        "__closing",
        "__extra_attributes",
    )

    def __init__(self, backend: AsyncBackend, transport: asyncio.DatagramTransport, protocol: DatagramListenerProtocol) -> None:
        super().__init__()

        socket: asyncio.trsock.TransportSocket | None = transport.get_extra_info("socket")
        if socket is None:
            raise AssertionError("transport must be a socket transport")

        self.__backend: AsyncBackend = backend
        self.__transport: asyncio.DatagramTransport = transport
        self.__protocol: DatagramListenerProtocol = protocol

        # asyncio.DatagramTransport.is_closing() can suddently become true if there is something wrong with the socket
        # even if transport.close() was never called.
        # To bypass this side effect, we use our own flag.
        self.__closing: bool = False

        self.__extra_attributes = MappingProxyType(socket_tools._get_socket_extra(socket, wrap_in_proxy=False))

    def __del__(self, *, _warn: _utils.WarnCallback = warnings.warn) -> None:
        try:
            transport = self.__transport
        except AttributeError:  # pragma: no cover
            # Technically possible but not with the common usage because this constructor does not raise.
            return
        if not transport.is_closing():
            _warn(f"unclosed listener {self!r}", ResourceWarning, source=self)
            transport.close()

    def is_closing(self) -> bool:
        return self.__closing

    async def aclose(self) -> None:
        self.__closing = True
        if not self.__transport.is_closing():
            self.__transport.close()
        await asyncio.shield(self.__protocol._get_close_waiter())

    async def serve(
        self,
        handler: Callable[[bytes, _RetAddress], Coroutine[Any, Any, None]],
        task_group: TaskGroup | None = None,
    ) -> NoReturn:
        async with self.__backend.create_task_group() if task_group is None else contextlib.nullcontext(task_group) as task_group:
            await self.__protocol.serve(handler, task_group)

        raise AssertionError("Expected code to be unreachable.")

    async def send_to(self, data: bytes | bytearray | memoryview, address: _Address) -> None:
        assert address is not None, "Address is None"  # nosec assert_used
        self.__transport.sendto(data, address)
        await self.__protocol.writer_drain()

    def backend(self) -> AsyncBackend:
        return self.__backend

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__extra_attributes


@dataclasses.dataclass(eq=False, frozen=True, slots=True)
class _DatagramListenerServeContext:
    datagram_handler: Callable[[bytes, _RetAddress], Coroutine[Any, Any, None]]
    task_group: TaskGroup

    def handle(self, data: bytes, addr: _RetAddress) -> None:
        self.task_group.start_soon(self.datagram_handler, data, addr)


class DatagramListenerProtocol(asyncio.DatagramProtocol):
    __slots__ = (
        "__loop",
        "__datagram_serve_ctx",
        "__delayed_datagrams_queue",
        "__transport",
        "__closed",
        "__write_flow",
        "__connection_lost",
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
        self.__delayed_datagrams_queue: collections.deque[tuple[bytes, _RetAddress]] = collections.deque()
        self.__transport: asyncio.DatagramTransport | None = None
        self.__closed: asyncio.Future[None] = loop.create_future()
        self.__write_flow: WriteFlowControl
        self.__connection_lost: bool = False
        self.__serve_forever_fut: asyncio.Future[NoReturn] = loop.create_future()

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:  # type: ignore[override]
        assert not self.__connection_lost, "connection_lost() was called"  # nosec assert_used
        assert self.__transport is None, "Transport already set"  # nosec assert_used
        self.__transport = transport
        self.__write_flow = WriteFlowControl(self.__transport, self.__loop)
        _monkeypatch_transport(self.__transport, self.__loop)

    def connection_lost(self, exc: Exception | None) -> None:
        self.__connection_lost = True
        self.__serve_forever_fut.cancel(msg="connection_lost()")

        if not self.__closed.done():
            self.__closed.set_result(None)

        self.__write_flow.connection_lost(exc)

        self.__transport = None
        self.__delayed_datagrams_queue.clear()

    def datagram_received(self, data: bytes, addr: _RetAddress) -> None:
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
        handler: Callable[[bytes, _RetAddress], Coroutine[Any, Any, None]],
        task_group: TaskGroup,
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
        self.__write_flow.pause_writing()

    def resume_writing(self) -> None:
        self.__write_flow.resume_writing()

    async def writer_drain(self) -> None:
        await self.__write_flow.drain()

    def _get_close_waiter(self) -> asyncio.Future[None]:
        return self.__closed

    def _get_loop(self) -> asyncio.AbstractEventLoop:
        return self.__loop

    def _writing_paused(self) -> bool:
        return self.__write_flow.writing_paused()
