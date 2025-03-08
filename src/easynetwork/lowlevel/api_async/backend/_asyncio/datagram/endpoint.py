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

__all__ = [
    "DatagramEndpoint",
    "DatagramEndpointProtocol",
    "create_datagram_endpoint",
]

import asyncio
import asyncio.base_events
import asyncio.trsock
import errno as _errno
import socket as _socket
import traceback
import warnings
from typing import TYPE_CHECKING, Any, final

from ..... import _unix_utils, _utils
from .._flow_control import WriteFlowControl

if TYPE_CHECKING:
    from socket import _Address, _RetAddress


async def create_datagram_endpoint(
    *,
    family: int = 0,
    local_addr: tuple[str, int] | str | None = None,
    remote_addr: tuple[str, int] | str | None = None,
    reuse_port: bool | None = None,
    sock: _socket.socket | None = None,
) -> DatagramEndpoint:
    loop = asyncio.get_running_loop()
    recv_queue: asyncio.Queue[tuple[bytes, _RetAddress] | None] = asyncio.Queue()
    exception_queue: asyncio.Queue[Exception] = asyncio.Queue()
    flags: int = 0
    if remote_addr is not None and not _unix_utils.is_unix_socket_family(family):
        flags |= _socket.AI_PASSIVE

    transport, protocol = await loop.create_datagram_endpoint(
        _utils.make_callback(DatagramEndpointProtocol, loop=loop, recv_queue=recv_queue, exception_queue=exception_queue),
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
        recv_queue: asyncio.Queue[tuple[bytes, _RetAddress] | None],
        exception_queue: asyncio.Queue[Exception],
    ) -> None:
        super().__init__()
        self.__recv_queue: asyncio.Queue[tuple[bytes, _RetAddress] | None] = recv_queue
        self.__exception_queue: asyncio.Queue[Exception] = exception_queue
        self.__transport: asyncio.DatagramTransport = transport
        self.__protocol: DatagramEndpointProtocol = protocol

    def __del__(self, *, _warn: _utils.WarnCallback = warnings.warn) -> None:
        try:
            transport = self.__transport
        except AttributeError:  # pragma: no cover
            # Technically possible but not with the common usage because this constructor does not raise.
            return
        if not transport.is_closing():
            _warn(f"unclosed endpoint {self!r}", ResourceWarning, source=self)
            transport.close()

    def close_nowait(self) -> None:
        if not self.__transport.is_closing():
            self.__transport.close()

    async def aclose(self) -> None:
        self.close_nowait()
        await asyncio.shield(self.__protocol._get_close_waiter())

    def is_closing(self) -> bool:
        return self.__transport.is_closing()

    async def recvfrom(self) -> tuple[bytes, _RetAddress]:
        if self.__transport.is_closing():
            try:
                data_and_address = self.__recv_queue.get_nowait()
            except asyncio.QueueEmpty:
                data_and_address = None
            if data_and_address is None:
                self.__check_exceptions()
                raise _utils.error_from_errno(_errno.ECONNABORTED)
        else:
            data_and_address = await self.__recv_queue.get()
            if data_and_address is None:
                # Woken up because an error occurred ?
                self.__check_exceptions()

                # Connection lost otherwise
                assert self.__transport.is_closing()  # nosec assert_used
                raise _utils.error_from_errno(_errno.ECONNABORTED)
        return data_and_address

    async def sendto(self, data: bytes | bytearray | memoryview, address: _Address | None = None, /) -> None:
        self.__transport.sendto(data, address)
        await self.__protocol._drain_helper()

    def get_extra_info(self, name: str, default: Any = None) -> Any:
        return self.__transport.get_extra_info(name, default)

    def __check_exceptions(self) -> None:
        exc: BaseException | None = None
        try:
            exc = self.__exception_queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
        else:
            raise exc
        finally:
            del exc


class DatagramEndpointProtocol(asyncio.DatagramProtocol):
    __slots__ = (
        "__loop",
        "__recv_queue",
        "__exception_queue",
        "__transport",
        "__write_flow",
        "__closed",
        "__connection_lost",
    )

    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop | None = None,
        recv_queue: asyncio.Queue[tuple[bytes, _RetAddress] | None],
        exception_queue: asyncio.Queue[Exception],
    ) -> None:
        super().__init__()
        if loop is None:
            loop = asyncio.get_running_loop()
        self.__loop: asyncio.AbstractEventLoop = loop
        self.__recv_queue: asyncio.Queue[tuple[bytes, _RetAddress] | None] = recv_queue
        self.__exception_queue: asyncio.Queue[Exception] = exception_queue
        self.__transport: asyncio.DatagramTransport | None = None
        self.__closed: asyncio.Future[None] = loop.create_future()
        self.__write_flow: WriteFlowControl
        self.__connection_lost: bool = False

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:  # type: ignore[override]
        assert not self.__connection_lost, "connection_lost() was called"  # nosec assert_used
        assert self.__transport is None, "Transport already set"  # nosec assert_used
        self.__transport = transport
        self.__write_flow = WriteFlowControl(self.__transport, self.__loop)
        _monkeypatch_transport(transport, self.__loop)

    def connection_lost(self, exc: Exception | None) -> None:
        self.__connection_lost = True

        if not self.__closed.done():
            self.__closed.set_result(None)

        self.__write_flow.connection_lost(exc)

        if self.__transport is not None:
            self.__transport = None
            self.__recv_queue.put_nowait(None)  # Wake up endpoint
            if exc is not None:
                self.__exception_queue.put_nowait(exc)

    def datagram_received(self, data: bytes, addr: _RetAddress) -> None:
        if self.__transport is not None:
            self.__recv_queue.put_nowait((data, addr))

    def error_received(self, exc: Exception) -> None:
        if self.__transport is not None:
            self.__loop.call_soon(traceback.clear_frames, exc.__traceback__)
            self.__exception_queue.put_nowait(exc)
            self.__recv_queue.put_nowait(None)  # Wake up endpoint

    def pause_writing(self) -> None:
        self.__write_flow.pause_writing()

    def resume_writing(self) -> None:
        self.__write_flow.resume_writing()

    async def _drain_helper(self) -> None:
        await self.__write_flow.drain()

    def _get_close_waiter(self) -> asyncio.Future[None]:
        return self.__closed

    def _get_loop(self) -> asyncio.AbstractEventLoop:
        return self.__loop

    def _writing_paused(self) -> bool:
        return self.__write_flow.writing_paused()


def _monkeypatch_transport(transport: asyncio.DatagramTransport, loop: asyncio.AbstractEventLoop) -> None:
    if isinstance(loop, asyncio.base_events.BaseEventLoop) and hasattr(transport, "_address"):
        # There is an asyncio issue where the private address attribute is not updated with the actual remote address
        # if the transport is instanciated with an external socket:
        #     await loop.create_datagram_endpoint(sock=my_socket)
        #
        # This is a monkeypatch to force update the internal address attribute
        peername: _RetAddress | None = transport.get_extra_info("peername", None)
        if peername is not None and getattr(transport, "_address") != peername:
            setattr(transport, "_address", peername)
