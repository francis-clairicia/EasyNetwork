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

__all__ = ["TrioStreamSocketAdapter"]

import errno as _errno
import itertools
import warnings
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, final

import trio

from ..... import _utils, constants, socket as socket_tools
from ....transports.abc import AsyncStreamTransport
from ...abc import AsyncBackend
from .._trio_utils import convert_trio_resource_errors
from ._sendmsg import supports_async_socket_sendmsg

if TYPE_CHECKING:
    from _typeshed import WriteableBuffer


@final
class TrioStreamSocketAdapter(AsyncStreamTransport):
    __slots__ = (
        "__backend",
        "__stream",
        "__extra_attributes",
    )

    def __init__(self, backend: AsyncBackend, stream: trio.SocketStream) -> None:
        super().__init__()

        self.__backend: AsyncBackend = backend
        self.__stream: trio.SocketStream = stream
        self.__extra_attributes = MappingProxyType(socket_tools._get_socket_extra(stream.socket))

    def __del__(self, *, _warn: _utils.WarnCallback = warnings.warn) -> None:
        try:
            stream = self.__stream
        except AttributeError:  # pragma: no cover
            # Technically possible but not with the common usage because this constructor does not raise.
            stream = None
        if stream is not None and stream.socket.fileno() >= 0:
            _warn(f"unclosed transport {self!r}", ResourceWarning, source=self)
            stream.socket.close()

    async def aclose(self) -> None:
        await self.__stream.aclose()

    def is_closing(self) -> bool:
        return self.__stream.socket.fileno() < 0

    async def recv(self, bufsize: int) -> bytes:
        with convert_trio_resource_errors(broken_resource_errno=_errno.ECONNABORTED):
            return await self.__stream.receive_some(bufsize)

    async def recv_into(self, buffer: WriteableBuffer) -> int:
        return await self.__stream.socket.recv_into(buffer)

    async def send_all(self, data: bytes | bytearray | memoryview) -> None:
        with convert_trio_resource_errors(broken_resource_errno=_errno.ECONNABORTED):
            return await self.__stream.send_all(data)

    async def send_all_from_iterable(self, iterable_of_data: Iterable[bytes | bytearray | memoryview]) -> None:
        if constants.SC_IOV_MAX <= 0:
            return await super().send_all_from_iterable(iterable_of_data)

        socket = self.__stream.socket
        if not supports_async_socket_sendmsg(socket):
            return await super().send_all_from_iterable(iterable_of_data)

        buffers: deque[memoryview] = deque(map(memoryview, iterable_of_data))  # type: ignore[arg-type]
        del iterable_of_data

        if not buffers:
            return await self.send_all(b"")

        while buffers:
            # Do not send the islice directly because if sendmsg() blocks,
            # it would retry with an already consumed iterator.
            sent = await socket.sendmsg(list(itertools.islice(buffers, constants.SC_IOV_MAX)))
            _utils.adjust_leftover_buffer(buffers, sent)

    async def send_eof(self) -> None:
        with convert_trio_resource_errors(broken_resource_errno=_errno.ECONNABORTED):
            await self.__stream.send_eof()

    def backend(self) -> AsyncBackend:
        return self.__backend

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__extra_attributes
