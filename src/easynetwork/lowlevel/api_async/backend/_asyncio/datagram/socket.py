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

__all__ = ["AsyncioTransportDatagramSocketAdapter"]

import asyncio
import asyncio.trsock
import socket as _socket
import sys
import warnings
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any, final

from ..... import _utils, socket as socket_tools
from ....transports.abc import AsyncDatagramTransport
from ...abc import AsyncBackend
from .endpoint import DatagramEndpoint


@final
class AsyncioTransportDatagramSocketAdapter(AsyncDatagramTransport):
    __slots__ = (
        "__backend",
        "__endpoint",
        "__closing",
        "__extra_attributes",
    )

    def __init__(self, backend: AsyncBackend, endpoint: DatagramEndpoint) -> None:
        super().__init__()

        socket: asyncio.trsock.TransportSocket | None = endpoint.get_extra_info("socket")
        if socket is None:
            raise AssertionError("transport must be a socket transport")

        self.__backend: AsyncBackend = backend
        self.__endpoint: DatagramEndpoint = endpoint

        # asyncio.DatagramTransport.is_closing() can suddently become true if there is something wrong with the socket
        # even if transport.close() was never called.
        # To bypass this side effect, we use our own flag.
        self.__closing: bool = False

        self.__extra_attributes = MappingProxyType(socket_tools._get_socket_extra(socket, wrap_in_proxy=False))

    def __del__(self, *, _warn: _utils.WarnCallback = warnings.warn) -> None:
        try:
            endpoint = self.__endpoint
        except AttributeError:  # pragma: no cover
            # Technically possible but not with the common usage because this constructor does not raise.
            return
        if not endpoint.is_closing():
            _warn(f"unclosed transport {self!r}", ResourceWarning, source=self)
            endpoint.close_nowait()

    async def aclose(self) -> None:
        self.__closing = True
        await self.__endpoint.aclose()

    def is_closing(self) -> bool:
        return self.__closing

    async def recv(self) -> bytes:
        data, _ = await self.__endpoint.recvfrom()
        return data

    async def send(self, data: bytes | bytearray | memoryview) -> None:
        await self.__endpoint.sendto(data, None)

    def backend(self) -> AsyncBackend:
        return self.__backend

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__extra_attributes


if sys.platform != "win32" and hasattr(_socket, "AF_UNIX"):

    __all__ += ["RawUnixDatagramSocketAdapter"]

    from collections.abc import Iterable
    from typing import TYPE_CHECKING

    from ..... import _unix_utils, constants
    from .. import _base_raw_transport

    if TYPE_CHECKING:
        from _typeshed import ReadableBuffer

    @final
    class RawUnixDatagramSocketAdapter(AsyncDatagramTransport, _base_raw_transport.BaseRawSocketTransport):
        __slots__ = ()

        def __init__(
            self,
            backend: AsyncBackend,
            socket: _socket.socket,
        ) -> None:
            _unix_utils.check_unix_socket_family(socket.family)
            if socket.type != _socket.SOCK_DGRAM:
                raise ValueError("A 'SOCK_DGRAM' socket is expected")

            super().__init__(backend, socket)

        async def recv(self) -> bytes:
            return await self._sock_recv(
                "recv",
                try_async_recv=lambda loop, sock: loop.sock_recv(sock, constants.MAX_DATAGRAM_BUFSIZE),
                recv=lambda sock: sock.recv(constants.MAX_DATAGRAM_BUFSIZE),
            )

        if hasattr(_socket.socket, "recvmsg"):  # pragma: no branch

            async def recv_with_ancillary(self, ancillary_bufsize: int) -> tuple[bytes, list[tuple[int, int, bytes]]]:
                msg, ancdata, _, _ = await self._sock_recv(
                    "recv_with_ancillary",
                    recv=lambda sock: sock.recvmsg(constants.MAX_DATAGRAM_BUFSIZE, ancillary_bufsize),
                )
                return msg, ancdata

        async def send(self, data: bytes | bytearray | memoryview) -> None:
            await self._sock_send("send", send=lambda sock: sock.send(data))

        if hasattr(_socket.socket, "sendmsg"):  # pragma: no branch

            async def send_with_ancillary(
                self,
                data: bytes | bytearray | memoryview,
                ancillary_data: Iterable[tuple[int, int, ReadableBuffer]],
            ) -> None:
                if hasattr(ancillary_data, "__next__"):
                    # Do not send the iterator directly because if sendmsg() blocks,
                    # it would retry with an already consumed iterator.
                    ancillary_data = list(ancillary_data)

                await self._sock_send("send_with_ancillary", send=lambda sock: sock.sendmsg([data], ancillary_data))
