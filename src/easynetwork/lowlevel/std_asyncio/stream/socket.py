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

__all__ = ["AsyncioTransportBufferedStreamSocketAdapter", "AsyncioTransportStreamSocketAdapter"]

import asyncio
import collections
import errno as _errno
from collections import ChainMap
from collections.abc import Callable, Iterable, Mapping
from typing import TYPE_CHECKING, Any, final

from ....exceptions import UnsupportedOperation
from ... import _utils, socket as socket_tools
from ...api_async.transports import abc as transports
from .._asyncio_utils import add_flowcontrol_defaults
from ..tasks import TaskUtils

if TYPE_CHECKING:
    import asyncio.trsock
    import ssl as _typing_ssl

    from _typeshed import WriteableBuffer


@final
class AsyncioTransportStreamSocketAdapter(transports.AsyncStreamTransport):
    __slots__ = (
        "__reader",
        "__writer",
        "__socket",
        "__closing",
        "__over_ssl",
    )

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        super().__init__()
        self.__reader: asyncio.StreamReader = reader
        self.__writer: asyncio.StreamWriter = writer
        self.__over_ssl: bool = writer.get_extra_info("sslcontext") is not None

        socket: asyncio.trsock.TransportSocket | None = writer.get_extra_info("socket")
        assert socket is not None, "Writer transport must be a socket transport"  # nosec assert_used
        self.__socket: asyncio.trsock.TransportSocket = socket

        # asyncio.Transport.is_closing() can suddently become true if there is something wrong with the socket
        # even if transport.close() was never called.
        # To bypass this side effect, we use our own flag.
        self.__closing: bool = False

    async def aclose(self) -> None:
        self.__closing = True
        if self.__writer.is_closing():
            # Only wait for it.
            try:
                await self.__writer.wait_closed()
            except OSError:
                pass
            return

        try:
            if self.__writer.can_write_eof():
                self.__writer.write_eof()
        except OSError:
            pass
        finally:
            self.__writer.close()
        try:
            await self.__writer.wait_closed()
        except OSError:
            pass
        except asyncio.CancelledError:
            if self.__over_ssl:
                self.__writer.transport.abort()
            raise

    def is_closing(self) -> bool:
        return self.__closing

    async def recv(self, bufsize: int) -> bytes:
        if bufsize < 0:
            raise ValueError("'bufsize' must be a positive or null integer")
        return await self.__reader.read(bufsize)

    async def send_all(self, data: bytes | bytearray | memoryview) -> None:
        self.__writer.write(data)
        await self.__writer.drain()

    async def send_all_from_iterable(self, iterable_of_data: Iterable[bytes | bytearray | memoryview]) -> None:
        self.__writer.writelines(iterable_of_data)
        await self.__writer.drain()

    async def send_eof(self) -> None:
        if not self.__writer.can_write_eof():
            raise UnsupportedOperation("transport does not support sending EOF")
        self.__writer.write_eof()
        await TaskUtils.coro_yield()

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        socket = self.__socket
        socket_extra: dict[Any, Callable[[], Any]] = socket_tools._get_socket_extra(socket, wrap_in_proxy=False)

        ssl_obj: _typing_ssl.SSLObject | _typing_ssl.SSLSocket | None = self.__writer.get_extra_info("ssl_object")
        if ssl_obj is None:
            return socket_extra
        return ChainMap(
            socket_extra,
            socket_tools._get_tls_extra(ssl_obj),
            {socket_tools.TLSAttribute.standard_compatible: lambda: True},
        )


@final
class AsyncioTransportBufferedStreamSocketAdapter(transports.AsyncStreamTransport, transports.AsyncBufferedStreamReadTransport):
    __slots__ = (
        "__transport",
        "__protocol",
        "__socket",
        "__closing",
        "__over_ssl",
    )

    def __init__(
        self,
        transport: asyncio.Transport,
        protocol: StreamReaderBufferedProtocol,
    ) -> None:
        super().__init__()
        self.__transport: asyncio.Transport = transport
        self.__protocol: StreamReaderBufferedProtocol = protocol
        self.__over_ssl: bool = transport.get_extra_info("sslcontext") is not None

        socket: asyncio.trsock.TransportSocket | None = transport.get_extra_info("socket")
        assert socket is not None, "Writer transport must be a socket transport"  # nosec assert_used
        self.__socket: asyncio.trsock.TransportSocket = socket

        # asyncio.Transport.is_closing() can suddently become true if there is something wrong with the socket
        # even if transport.close() was never called.
        # To bypass this side effect, we use our own flag.
        self.__closing: bool = False

        # Disable in-memory byte buffering.
        if self.__over_ssl:
            transport.set_write_buffer_limits(1)
        else:
            transport.set_write_buffer_limits(0)

    async def aclose(self) -> None:
        self.__closing = True
        if self.__transport.is_closing():
            # Only wait for it.
            try:
                await asyncio.shield(self.__protocol._get_close_waiter())
            except OSError:
                pass
            return

        try:
            if self.__transport.can_write_eof():
                self.__transport.write_eof()
        except OSError:
            pass
        finally:
            self.__transport.close()
        try:
            await asyncio.shield(self.__protocol._get_close_waiter())
        except OSError:
            pass
        except asyncio.CancelledError:
            if self.__over_ssl:
                self.__transport.abort()
            raise

    def is_closing(self) -> bool:
        return self.__closing

    async def recv(self, bufsize: int) -> bytes:
        return await self.__protocol.receive_data(bufsize)

    async def recv_into(self, buffer: WriteableBuffer) -> int:
        return await self.__protocol.receive_data_into(buffer)

    async def send_all(self, data: bytes | bytearray | memoryview) -> None:
        self.__transport.write(data)
        if self.__transport.is_closing():
            await TaskUtils.coro_yield()
        await self.__protocol.writer_drain()

    async def send_all_from_iterable(self, iterable_of_data: Iterable[bytes | bytearray | memoryview]) -> None:
        self.__transport.writelines(iterable_of_data)
        if self.__transport.is_closing():
            await TaskUtils.coro_yield()
        await self.__protocol.writer_drain()

    async def send_eof(self) -> None:
        if not self.__transport.can_write_eof():
            raise UnsupportedOperation("transport does not support sending EOF")
        self.__transport.write_eof()
        await TaskUtils.coro_yield()

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        socket = self.__socket
        socket_extra: dict[Any, Callable[[], Any]] = socket_tools._get_socket_extra(socket, wrap_in_proxy=False)

        ssl_obj: _typing_ssl.SSLObject | _typing_ssl.SSLSocket | None = self.__transport.get_extra_info("ssl_object")
        if ssl_obj is None:
            return socket_extra
        return ChainMap(
            socket_extra,
            socket_tools._get_tls_extra(ssl_obj),
            {socket_tools.TLSAttribute.standard_compatible: lambda: True},
        )


class StreamReaderBufferedProtocol(asyncio.BufferedProtocol):
    __slots__ = (
        "__loop",
        "__buffer",
        "__buffer_view",
        "__buffer_nbytes_written",
        "__transport",
        "__closed",
        "__read_waiter",
        "__drain_waiters",
        "__write_paused",
        "__read_paused",
        "__read_high_water",
        "__read_low_water",
        "__connection_lost",
        "__connection_lost_exception",
        "__eof_reached",
        "__over_ssl",
    )

    max_size: int = 256 * 1024

    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        super().__init__()
        if loop is None:
            loop = asyncio.get_running_loop()
        self.__loop: asyncio.AbstractEventLoop = loop
        self.__buffer: bytearray | None = bytearray(self.max_size)
        self.__buffer_view: memoryview = memoryview(self.__buffer)
        self.__buffer_nbytes_written: int = 0
        self.__transport: asyncio.Transport | None = None
        self.__closed: asyncio.Future[None] = loop.create_future()
        self.__read_waiter: asyncio.Future[None] | None = None
        self.__drain_waiters: collections.deque[asyncio.Future[None]] = collections.deque()
        self.__write_paused: bool = False
        self.__read_paused: bool = False
        self.__connection_lost: bool = False
        self.__connection_lost_exception: Exception | None = None
        self.__eof_reached: bool = False
        self.__over_ssl: bool = False
        self._compute_read_buffer_limits()

    def connection_made(self, transport: asyncio.Transport) -> None:  # type: ignore[override]
        assert self.__transport is None, "Transport already set"  # nosec assert_used
        self.__transport = transport
        self.__over_ssl = transport.get_extra_info("sslcontext") is not None

    def connection_lost(self, exc: Exception | None) -> None:
        self.__connection_lost = True
        self.__connection_lost_exception = exc
        if exc is None:
            self.__eof_reached = True
        else:
            self.__buffer_nbytes_written = 0
        self._maybe_release_buffer()

        if not self.__closed.done():
            self.__closed.set_result(None)

        self._wakeup_read_waiter(exc)
        self._wakeup_write_waiters(exc)

        self.__transport = None

    def get_buffer(self, sizehint: int) -> WriteableBuffer:
        # Ignore sizehint, the buffer is already at its maximum size.
        # Returns unused buffer part
        if self.__buffer is None:
            raise BufferError("get_buffer() called after connection_lost()")
        return self.__buffer_view[self.__buffer_nbytes_written :]

    def buffer_updated(self, nbytes: int) -> None:
        assert not self.__connection_lost, "buffer_updated() after connection_lost()"  # nosec assert_used
        assert not self.__eof_reached, "buffer_updated() after eof_received()"  # nosec assert_used

        self.__buffer_nbytes_written += nbytes
        assert 0 <= self.__buffer_nbytes_written <= self.__buffer_view.nbytes  # nosec assert_used
        self._wakeup_read_waiter(None)
        self._maybe_pause_transport()

    def eof_received(self) -> bool:
        self.__eof_reached = True
        self._wakeup_read_waiter(None)
        if self.__over_ssl:
            # Prevent a warning in SSLProtocol.eof_received:
            # "returning true from eof_received()
            # has no effect when using ssl"
            return False
        return True

    async def receive_data(self, bufsize: int, /) -> bytes:
        if self.__connection_lost:
            if self.__connection_lost_exception is not None:
                raise self.__connection_lost_exception
        if bufsize == 0:
            return b""
        if bufsize < 0:
            raise ValueError("'bufsize' must be a positive or null integer")
        if not self.__buffer_nbytes_written and not self.__eof_reached:
            await self._wait_for_data("receive_data")

        nbytes_written = self.__buffer_nbytes_written
        if nbytes_written:
            protocol_buffer_written = self.__buffer_view[:nbytes_written]
            data = bytes(protocol_buffer_written[:bufsize])
            if (unused := nbytes_written - bufsize) > 0:
                protocol_buffer_written[:unused] = protocol_buffer_written[-unused:]
                self.__buffer_nbytes_written = unused
            else:
                self.__buffer_nbytes_written = 0
        else:
            data = b""
        self._maybe_resume_transport()
        return data

    async def receive_data_into(self, buffer: WriteableBuffer, /) -> int:
        if self.__connection_lost:
            if self.__connection_lost_exception is not None:
                raise self.__connection_lost_exception
        with memoryview(buffer).cast("B") as buffer:
            if not buffer.nbytes:
                return 0
            if not self.__buffer_nbytes_written and not self.__eof_reached:
                await self._wait_for_data("receive_data_into")

            nbytes_written = self.__buffer_nbytes_written
            if nbytes_written:
                protocol_buffer_written = self.__buffer_view[:nbytes_written]
                bufsize_offset = nbytes_written - buffer.nbytes
                if bufsize_offset > 0:
                    nbytes_written = buffer.nbytes
                    buffer[:] = protocol_buffer_written[:nbytes_written]
                    protocol_buffer_written[:bufsize_offset] = protocol_buffer_written[-bufsize_offset:]
                    self.__buffer_nbytes_written = bufsize_offset
                else:
                    buffer[:nbytes_written] = protocol_buffer_written
                    self.__buffer_nbytes_written = 0

        self._maybe_resume_transport()
        return nbytes_written

    async def _wait_for_data(self, requester: str) -> None:
        if self.__read_waiter is not None:
            raise RuntimeError(f"{requester}() called while another coroutine is already waiting for incoming data")

        assert not self.__eof_reached, "_wait_for_data after EOF"  # nosec assert_used
        assert not self.__read_paused, "transport reading is paused"  # nosec assert_used

        if self.__transport is None:
            # happening if transport.pause_reading() raises NotImplementedError
            raise _utils.error_from_errno(_errno.ECONNABORTED)

        self.__read_waiter = self.__loop.create_future()
        try:
            await self.__read_waiter
        finally:
            self.__read_waiter = None

    def _wakeup_read_waiter(self, exc: Exception | None) -> None:
        if (waiter := self.__read_waiter) is not None:
            if not waiter.done():
                if exc is None:
                    waiter.set_result(None)
                else:
                    waiter.set_exception(exc)

    def _get_read_buffer_size(self) -> int:
        return self.__buffer_nbytes_written

    def _get_read_buffer_limits(self) -> tuple[int, int]:
        return (self.__read_low_water, self.__read_high_water)

    def _compute_read_buffer_limits(self) -> None:
        max_size_in_kb = self.max_size // 1024
        default_water_size = max_size_in_kb * 3 // 4
        high, low = add_flowcontrol_defaults(None, None, default_water_size)
        self.__read_high_water: int = high
        self.__read_low_water: int = low

    def _maybe_pause_transport(self) -> None:
        if (
            self.__buffer_nbytes_written >= self.__read_high_water
            and not self.__read_paused
            and (transport := self.__transport) is not None
        ):
            try:
                transport.pause_reading()
            except NotImplementedError:
                # From asyncio.StreamReader: The transport can't be paused.
                # We'll just have to buffer all data.
                # Forget the transport so we don't keep trying.
                self.__transport = None
            else:
                self.__read_paused = True

    def _maybe_resume_transport(self) -> None:
        if self.__connection_lost:
            self._maybe_release_buffer()
        elif (
            self.__read_paused
            and (transport := self.__transport) is not None
            and self.__buffer_nbytes_written <= self.__read_low_water
        ):
            transport.resume_reading()
            self.__read_paused = False

    def _maybe_release_buffer(self) -> None:
        if not self.__buffer_nbytes_written and self.__connection_lost:
            self.__buffer_view.release()
            self.__buffer = None

    def pause_writing(self) -> None:
        self.__write_paused = True

    def resume_writing(self) -> None:
        self.__write_paused = False

        self._wakeup_write_waiters(None)

    async def writer_drain(self) -> None:
        if self.__connection_lost:
            if self.__connection_lost_exception is not None:
                raise self.__connection_lost_exception
            raise _utils.error_from_errno(_errno.ECONNRESET)
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

    def _reading_paused(self) -> bool:
        return self.__read_paused

    def _writing_paused(self) -> bool:
        return self.__write_paused
