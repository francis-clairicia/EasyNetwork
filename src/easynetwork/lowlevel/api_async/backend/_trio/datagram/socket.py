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
"""trio engine for easynetwork.api_async"""

from __future__ import annotations

__all__ = ["TrioDatagramSocketAdapter"]

import errno as _errno
import socket as _socket
import sys
import warnings
from collections.abc import Callable, Iterable, Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, final

import trio

from ..... import _unix_utils, _utils, socket as socket_tools
from ....transports.abc import AsyncDatagramTransport
from ...abc import AsyncBackend
from .._trio_utils import convert_trio_resource_errors

if TYPE_CHECKING:
    from _typeshed import ReadableBuffer


@final
class TrioDatagramSocketAdapter(AsyncDatagramTransport):
    __slots__ = (
        "__backend",
        "__socket",
        "__extra_attributes",
    )

    from .....constants import MAX_DATAGRAM_BUFSIZE

    def __init__(self, backend: AsyncBackend, sock: trio.socket.SocketType) -> None:
        super().__init__()

        if sock.type != _socket.SOCK_DGRAM:
            raise ValueError("A 'SOCK_DGRAM' socket is expected")

        self.__backend: AsyncBackend = backend
        self.__socket: trio.socket.SocketType = sock
        self.__extra_attributes = MappingProxyType(socket_tools._get_socket_extra(sock))

    def __del__(self, *, _warn: _utils.WarnCallback = warnings.warn) -> None:
        try:
            socket = self.__socket
        except AttributeError:
            socket = None
        if socket is not None and socket.fileno() >= 0:
            _warn(f"unclosed transport {self!r}", ResourceWarning, source=self)
            socket.close()

    async def aclose(self) -> None:
        self.__socket.close()
        await trio.lowlevel.checkpoint()

    def is_closing(self) -> bool:
        return self.__socket.fileno() < 0

    async def recv(self) -> bytes:
        with convert_trio_resource_errors(broken_resource_errno=_errno.EBADF):
            return await self.__socket.recv(self.MAX_DATAGRAM_BUFSIZE)

    if sys.platform != "win32" or (not TYPE_CHECKING and hasattr(trio.socket.SocketType, "recvmsg")):

        async def recv_with_ancillary(self, ancillary_bufsize: int) -> tuple[bytes, list[tuple[int, int, bytes]]]:
            if not _unix_utils.is_unix_socket_family((socket := self.__socket).family):
                return await super().recv_with_ancillary(ancillary_bufsize)
            msg, ancdata, _, _ = await socket.recvmsg(self.MAX_DATAGRAM_BUFSIZE, ancillary_bufsize)
            return msg, ancdata

    async def send(self, data: bytes | bytearray | memoryview) -> None:
        with convert_trio_resource_errors(broken_resource_errno=_errno.EBADF):
            await self.__socket.send(data)

    if sys.platform != "win32" or (not TYPE_CHECKING and hasattr(trio.socket.SocketType, "sendmsg")):

        async def send_with_ancillary(
            self,
            data: bytes | bytearray | memoryview,
            ancillary_data: Iterable[tuple[int, int, ReadableBuffer]],
        ) -> None:
            if not _unix_utils.is_unix_socket_family((socket := self.__socket).family):
                return await super().send_with_ancillary(data, ancillary_data)
            if hasattr(ancillary_data, "__next__"):
                # Do not send the iterator directly because if sendmsg() blocks,
                # it would retry with an already consumed iterator.
                ancillary_data = list(ancillary_data)

            await socket.sendmsg([data], ancillary_data)

    def backend(self) -> AsyncBackend:
        return self.__backend

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__extra_attributes
