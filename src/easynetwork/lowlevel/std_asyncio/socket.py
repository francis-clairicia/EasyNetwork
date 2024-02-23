# Copyright 2021-2024, Francis Clairicia-Rose-Claire-Josephine
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

__all__ = ["AsyncSocket"]

import asyncio
import asyncio.trsock
import contextlib
import errno as _errno
import itertools
import socket as _socket
from collections import deque
from collections.abc import Iterable, Iterator
from typing import TYPE_CHECKING, Literal, Self, TypeAlias, cast

from ...exceptions import UnsupportedOperation
from .. import _utils, constants
from . import _asyncio_utils
from .tasks import CancelScope, TaskUtils

if TYPE_CHECKING:
    from types import TracebackType

    from _typeshed import ReadableBuffer, WriteableBuffer


_SocketTaskId: TypeAlias = Literal["accept", "send", "recv"]


class AsyncSocket:
    __slots__ = (
        "__socket",
        "__trsock",
        "__loop",
        "__scopes",
        "__waiters",
        "__close_waiter",
        "__weakref__",
    )

    def __init__(self, socket: _socket.socket, loop: asyncio.AbstractEventLoop) -> None:
        super().__init__()

        _utils.check_socket_no_ssl(socket)
        socket.setblocking(False)

        self.__socket: _socket.socket | None = socket
        self.__trsock: asyncio.trsock.TransportSocket = asyncio.trsock.TransportSocket(socket)
        self.__loop: asyncio.AbstractEventLoop = loop
        self.__scopes: set[CancelScope] = set()
        self.__waiters: dict[_SocketTaskId, asyncio.Future[None]] = {}
        self.__close_waiter: asyncio.Future[None] = loop.create_future()

    def __del__(self) -> None:
        try:
            socket: _socket.socket | None = self.__socket
        except AttributeError:
            return
        if socket is not None:
            socket.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    def is_closing(self) -> bool:
        return self.__socket is None

    async def aclose(self) -> None:
        socket = self.__socket

        if socket is None:
            await asyncio.shield(self.__close_waiter)
            return
        with contextlib.ExitStack() as stack:
            stack.callback(self.__close_waiter.set_result, None)
            stack.callback(socket.close)

            self.__socket = None

            del stack

            for scope in list(self.__scopes):
                scope.cancel()
                del scope
            futures_to_wait_for_completion: set[asyncio.Future[None]] = set(self.__waiters.values())
            if futures_to_wait_for_completion:
                await asyncio.wait(futures_to_wait_for_completion, return_when=asyncio.ALL_COMPLETED)

        await TaskUtils.coro_yield()

    async def accept(self) -> _socket.socket:
        listener_socket = self.__check_not_closed()
        with self.__conflict_detection("accept"):
            client_socket, _ = await self.__loop.sock_accept(listener_socket)
            return client_socket

    async def sendall(self, data: ReadableBuffer, /) -> None:
        socket = self.__check_not_closed()
        with self.__conflict_detection("send"):
            await self.__loop.sock_sendall(socket, data)

    async def sendmsg(self, buffers: Iterable[ReadableBuffer], /) -> None:
        socket = self.__check_not_closed()
        if constants.SC_IOV_MAX <= 0 or not _utils.supports_socket_sendmsg(_sock := socket):
            raise UnsupportedOperation("sendmsg() is not supported")

        with self.__conflict_detection("send"):
            loop = self.__loop
            buffers = cast("deque[memoryview]", deque(memoryview(data).cast("B") for data in buffers))

            sock_sendmsg = _sock.sendmsg
            del _sock

            while buffers:
                try:
                    sent: int = sock_sendmsg(itertools.islice(buffers, constants.SC_IOV_MAX))
                except (BlockingIOError, InterruptedError):
                    await _asyncio_utils.wait_until_writable(socket, loop)
                else:
                    _utils.adjust_leftover_buffer(buffers, sent)

    async def sendto(self, data: ReadableBuffer, address: _socket._Address, /) -> None:
        socket = self.__check_not_closed()
        with self.__conflict_detection("send"):
            await self.__loop.sock_sendto(socket, data, address)

    async def recv(self, bufsize: int, /) -> bytes:
        socket = self.__check_not_closed()
        with self.__conflict_detection("recv"):
            return await self.__loop.sock_recv(socket, bufsize)

    async def recv_into(self, buffer: WriteableBuffer, /) -> int:
        socket = self.__check_not_closed()
        with self.__conflict_detection("recv"):
            # NOTE: Workaround for an issue in asyncio.ProactorEventLoop which occurs because a call to Overlapped.WSARecvInto()
            # does not release the exported buffer (using PyBuffer_Release()) at the end of the function unless the
            # garbage collector clears the object.
            buffer = memoryview(buffer)

            return await self.__loop.sock_recv_into(socket, buffer)

    async def recvfrom(self, bufsize: int, /) -> tuple[bytes, _socket._RetAddress]:
        socket = self.__check_not_closed()
        with self.__conflict_detection("recv"):
            return await self.__loop.sock_recvfrom(socket, bufsize)

    async def shutdown(self, how: int, /) -> None:
        TaskUtils.check_current_event_loop(self.__loop)

        if how in {_socket.SHUT_RDWR, _socket.SHUT_WR}:
            while (waiter := self.__waiters.get("send")) is not None:
                try:
                    await asyncio.shield(waiter)
                finally:
                    waiter = None  # Break cyclic reference with raised exception

        socket: _socket.socket = self.__check_not_closed()
        socket.shutdown(how)
        await TaskUtils.coro_yield()

    @contextlib.contextmanager
    def __conflict_detection(self, task_id: _SocketTaskId) -> Iterator[None]:
        if task_id in self.__waiters:
            raise _utils.error_from_errno(_errno.EBUSY)

        TaskUtils.check_current_event_loop(self.__loop)

        with contextlib.ExitStack() as stack, CancelScope() as scope:
            self.__scopes.add(scope)
            stack.callback(self.__scopes.discard, scope)

            waiter: asyncio.Future[None] = self.__loop.create_future()
            stack.callback(waiter.set_result, None)
            self.__waiters[task_id] = waiter
            stack.callback(self.__waiters.pop, task_id)
            del waiter

            yield

        if scope.cancelled_caught():
            raise _utils.error_from_errno(_errno.EBADF)

    def __check_not_closed(self) -> _socket.socket:
        if (socket := self.__socket) is None:
            raise _utils.error_from_errno(_errno.EBADF)
        return socket

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        return self.__loop

    @property
    def socket(self) -> asyncio.trsock.TransportSocket:
        return self.__trsock
