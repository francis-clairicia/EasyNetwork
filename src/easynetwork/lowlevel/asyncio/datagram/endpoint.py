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

__all__ = [
    "DatagramEndpoint",
    "DatagramEndpointProtocol",
    "create_datagram_endpoint",
]

import asyncio
import asyncio.base_events
import collections
import errno as _errno
import socket as _socket
from typing import TYPE_CHECKING, Any, final

from ... import _utils
from ..tasks import TaskUtils

if TYPE_CHECKING:
    import asyncio.trsock


async def create_datagram_endpoint(
    *,
    family: int = 0,
    local_addr: tuple[str, int] | None = None,
    remote_addr: tuple[str, int] | None = None,
    reuse_port: bool = False,
    sock: _socket.socket | None = None,
) -> DatagramEndpoint:
    loop = asyncio.get_running_loop()
    recv_queue: asyncio.Queue[tuple[bytes, tuple[Any, ...]] | None] = asyncio.Queue()
    exception_queue: asyncio.Queue[Exception] = asyncio.Queue()
    flags: int = 0
    if remote_addr is not None:
        flags |= _socket.AI_PASSIVE

    transport, protocol = await loop.create_datagram_endpoint(
        lambda: DatagramEndpointProtocol(loop=loop, recv_queue=recv_queue, exception_queue=exception_queue),
        family=family,
        local_addr=local_addr,
        remote_addr=remote_addr,
        reuse_port=reuse_port,
        sock=sock,
        flags=flags,
    )

    return DatagramEndpoint(transport, protocol, recv_queue=recv_queue, exception_queue=exception_queue)


@final
class DatagramEndpoint:
    __slots__ = (
        "__recv_queue",
        "__exception_queue",
        "__transport",
        "__protocol",
        "__weakref__",
    )

    def __init__(
        self,
        transport: asyncio.DatagramTransport,
        protocol: DatagramEndpointProtocol,
        *,
        recv_queue: asyncio.Queue[tuple[bytes, tuple[Any, ...]] | None],
        exception_queue: asyncio.Queue[Exception],
    ) -> None:
        super().__init__()
        self.__recv_queue: asyncio.Queue[tuple[bytes, tuple[Any, ...]] | None] = recv_queue
        self.__exception_queue: asyncio.Queue[Exception] = exception_queue
        self.__transport: asyncio.DatagramTransport = transport
        self.__protocol: DatagramEndpointProtocol = protocol

    def close(self) -> None:
        self.__transport.close()

    async def wait_closed(self) -> None:
        await self.__protocol._get_close_waiter()

    async def aclose(self) -> None:
        self.close()
        await self.wait_closed()

    def is_closing(self) -> bool:
        return self.__transport.is_closing()

    async def recvfrom(self) -> tuple[bytes, tuple[Any, ...]]:
        self.__check_exceptions()
        if self.__transport.is_closing():
            try:
                data_and_address = self.__recv_queue.get_nowait()
            except asyncio.QueueEmpty:
                data_and_address = None
            if data_and_address is None:
                raise _utils.error_from_errno(_errno.ECONNABORTED)
            await TaskUtils.cancel_shielded_coro_yield()
        else:
            data_and_address = await self.__recv_queue.get()
            if data_and_address is None:
                # Woken up because an error occurred ?
                self.__check_exceptions()

                # Connection lost otherwise
                assert self.__transport.is_closing()  # nosec assert_used
                raise _utils.error_from_errno(_errno.ECONNABORTED)
        return data_and_address

    async def sendto(self, data: bytes | bytearray | memoryview, address: tuple[Any, ...] | None = None, /) -> None:
        self.__check_exceptions()
        if self.__transport.is_closing():
            raise _utils.error_from_errno(_errno.ECONNABORTED)
        self.__transport.sendto(data, address)
        await self.__protocol._drain_helper()

    def get_extra_info(self, name: str, default: Any = None) -> Any:
        return self.__transport.get_extra_info(name, default)

    def __check_exceptions(self) -> None:
        try:
            exc = self.__exception_queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
        else:
            try:
                raise exc
            finally:
                del exc

    @property
    @final
    def transport(self) -> asyncio.DatagramTransport:
        return self.__transport


class DatagramEndpointProtocol(asyncio.DatagramProtocol):
    __slots__ = (
        "__loop",
        "__recv_queue",
        "__exception_queue",
        "__transport",
        "__closed",
        "__drain_waiters",
        "__write_paused",
        "__connection_lost",
    )

    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop | None = None,
        recv_queue: asyncio.Queue[tuple[bytes, tuple[Any, ...]] | None],
        exception_queue: asyncio.Queue[Exception],
    ) -> None:
        super().__init__()
        if loop is None:
            loop = asyncio.get_running_loop()
        self.__loop: asyncio.AbstractEventLoop = loop
        self.__recv_queue: asyncio.Queue[tuple[bytes, tuple[Any, ...]] | None] = recv_queue
        self.__exception_queue: asyncio.Queue[Exception] = exception_queue
        self.__transport: asyncio.DatagramTransport | None = None
        self.__closed: asyncio.Future[None] = loop.create_future()
        self.__drain_waiters: collections.deque[asyncio.Future[None]] = collections.deque()
        self.__write_paused: bool = False
        self.__connection_lost: bool = False

    def __del__(self) -> None:  # pragma: no cover
        # Prevent reports about unhandled exceptions.
        try:
            closed = self.__closed
        except AttributeError:
            pass
        else:
            if closed.done() and not closed.cancelled():
                closed.exception()

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:  # type: ignore[override]
        assert self.__transport is None, "Transport already set"  # nosec assert_used
        self.__transport = transport
        self.__connection_lost = False
        _monkeypatch_transport(transport, self.__loop)

    def connection_lost(self, exc: Exception | None) -> None:
        self.__connection_lost = True

        if not self.__closed.done():
            self.__closed.set_result(None)

        for waiter in self.__drain_waiters:
            if not waiter.done():
                if exc is None:
                    waiter.set_result(None)
                else:
                    waiter.set_exception(exc)

        if self.__transport is not None:
            self.__recv_queue.put_nowait(None)  # Wake up endpoint
            if exc is not None:
                self.__exception_queue.put_nowait(exc)
            self.__transport.close()
            self.__transport = None

        super().connection_lost(exc)

    def datagram_received(self, data: bytes, addr: tuple[Any, ...]) -> None:
        if self.__transport is not None:
            self.__recv_queue.put_nowait((data, addr))

    def error_received(self, exc: Exception) -> None:
        if self.__transport is not None:
            self.__exception_queue.put_nowait(exc)
            self.__recv_queue.put_nowait(None)  # Wake up endpoint

    def pause_writing(self) -> None:
        assert not self.__write_paused  # nosec assert_used
        self.__write_paused = True

        super().pause_writing()

    def resume_writing(self) -> None:
        assert self.__write_paused  # nosec assert_used
        self.__write_paused = False

        for waiter in self.__drain_waiters:
            if not waiter.done():
                waiter.set_result(None)

        super().resume_writing()

    async def _drain_helper(self) -> None:
        if self.__connection_lost:
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

    def _get_close_waiter(self) -> asyncio.Future[None]:
        return self.__closed

    def _get_loop(self) -> asyncio.AbstractEventLoop:
        return self.__loop

    def _writing_paused(self) -> bool:
        return self.__write_paused


def _monkeypatch_transport(transport: asyncio.DatagramTransport, loop: asyncio.AbstractEventLoop) -> None:
    if isinstance(loop, asyncio.base_events.BaseEventLoop) and hasattr(transport, "_address"):
        # There is an asyncio issue where the private address attribute is not updated with the actual remote address
        # if the transport is instanciated with an external socket:
        #     await loop.create_datagram_endpoint(sock=my_socket)
        #
        # This is a monkeypatch to force update the internal address attribute
        peername: tuple[Any, ...] | None = transport.get_extra_info("peername", None)
        if peername is not None and getattr(transport, "_address") != peername:
            setattr(transport, "_address", peername)
