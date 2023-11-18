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

__all__ = ["AsyncioTransportStreamSocketAdapter", "RawStreamSocketAdapter"]

import asyncio
import socket as _socket
from collections import ChainMap
from collections.abc import Callable, Iterable, Mapping
from typing import TYPE_CHECKING, Any, final

from ....exceptions import UnsupportedOperation
from ... import socket as socket_tools
from ...api_async.transports import abc as transports
from ..socket import AsyncSocket

if TYPE_CHECKING:
    import asyncio.trsock
    import ssl as _typing_ssl


@final
class AsyncioTransportStreamSocketAdapter(transports.AsyncStreamTransport):
    __slots__ = (
        "__reader",
        "__writer",
        "__socket",
        "__closing",
    )

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        super().__init__()
        self.__reader: asyncio.StreamReader = reader
        self.__writer: asyncio.StreamWriter = writer

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
            if self.__writer.get_extra_info("sslcontext") is not None:
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
        iterable_of_data = list(iterable_of_data)
        if len(iterable_of_data) == 1:
            self.__writer.write(iterable_of_data[0])
        else:
            self.__writer.writelines(iterable_of_data)
        del iterable_of_data
        await self.__writer.drain()

    async def send_eof(self) -> None:
        if not self.__writer.can_write_eof():
            raise UnsupportedOperation("transport does not support sending EOF")
        self.__writer.write_eof()
        await asyncio.sleep(0)

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
class RawStreamSocketAdapter(transports.AsyncStreamTransport):
    __slots__ = ("__socket",)

    def __init__(
        self,
        socket: _socket.socket,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        super().__init__()

        if socket.type != _socket.SOCK_STREAM:
            raise ValueError("A 'SOCK_STREAM' socket is expected")

        self.__socket: AsyncSocket = AsyncSocket(socket, loop)

    async def aclose(self) -> None:
        try:
            await self.__socket.shutdown(_socket.SHUT_RDWR)
        except OSError:
            pass
        finally:
            await self.__socket.aclose()

    def is_closing(self) -> bool:
        return self.__socket.is_closing()

    async def recv(self, bufsize: int) -> bytes:
        return await self.__socket.recv(bufsize)

    async def send_all(self, data: bytes | bytearray | memoryview) -> None:
        await self.__socket.sendall(data)

    async def send_eof(self) -> None:
        await self.__socket.shutdown(_socket.SHUT_WR)

    async def send_all_from_iterable(self, iterable_of_data: Iterable[bytes | bytearray | memoryview]) -> None:
        try:
            await self.__socket.sendmsg(iterable_of_data)
        except UnsupportedOperation:
            await super().send_all_from_iterable(iterable_of_data)

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        socket = self.__socket.socket
        return socket_tools._get_socket_extra(socket, wrap_in_proxy=False)
