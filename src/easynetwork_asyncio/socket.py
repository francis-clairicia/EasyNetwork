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

__all__ = ["AsyncSocket"]

import asyncio
import asyncio.trsock
import contextlib
import errno as _errno
import socket as _socket
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, Literal, Self, TypeAlias
from weakref import WeakSet

from easynetwork.tools._utils import check_socket_no_ssl as _check_socket_no_ssl, error_from_errno as _error_from_errno

from .tasks import TaskUtils

if TYPE_CHECKING:
    from types import TracebackType

    from _typeshed import ReadableBuffer


_SocketTaskId: TypeAlias = Literal["accept", "send", "recv"]


class AsyncSocket:
    __slots__ = (
        "__socket",
        "__trsock",
        "__loop",
        "__tasks",
        "__waiters",
        "__close_waiter",
        "__shutdown_write",
        "__weakref__",
    )

    def __init__(self, socket: _socket.socket, loop: asyncio.AbstractEventLoop) -> None:
        super().__init__()

        _check_socket_no_ssl(socket)
        socket.setblocking(False)

        self.__socket: _socket.socket | None = socket
        self.__trsock: asyncio.trsock.TransportSocket = asyncio.trsock.TransportSocket(socket)
        self.__loop: asyncio.AbstractEventLoop = loop
        self.__tasks: WeakSet[asyncio.Task[Any]] = WeakSet()
        self.__waiters: dict[_SocketTaskId, asyncio.Future[None]] = {}
        self.__close_waiter: asyncio.Future[None] = loop.create_future()
        self.__shutdown_write: bool = False

    def __del__(self) -> None:  # pragma: no cover
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
        async with contextlib.AsyncExitStack() as stack:
            stack.callback(self.__close_waiter.set_result, None)
            stack.callback(socket.close)

            self.__socket = None

            del stack

            for task in list(self.__tasks):
                task.cancel()
                del task
            futures_to_wait_for_completion: set[asyncio.Future[None]] = set(self.__waiters.values())
            if futures_to_wait_for_completion:
                await asyncio.wait(futures_to_wait_for_completion, return_when=asyncio.ALL_COMPLETED)

        await asyncio.sleep(0)

    async def accept(self) -> tuple[_socket.socket, _socket._RetAddress]:
        with self.__conflict_detection("accept", abort_errno=_errno.EINTR) as socket:
            return await self.__loop.sock_accept(socket)

    async def sendall(self, data: ReadableBuffer, /) -> None:
        with self.__conflict_detection("send", abort_errno=_errno.ECONNABORTED) as socket:
            await self.__loop.sock_sendall(socket, data)

    async def sendto(self, data: ReadableBuffer, address: _socket._Address, /) -> None:
        with self.__conflict_detection("send", abort_errno=_errno.ECONNABORTED) as socket:
            await self.__loop.sock_sendto(socket, data, address)

    async def recv(self, bufsize: int, /) -> bytes:
        with self.__conflict_detection("recv", abort_errno=_errno.ECONNABORTED) as socket:
            return await self.__loop.sock_recv(socket, bufsize)

    async def recvfrom(self, bufsize: int, /) -> tuple[bytes, _socket._RetAddress]:
        with self.__conflict_detection("recv", abort_errno=_errno.ECONNABORTED) as socket:
            return await self.__loop.sock_recvfrom(socket, bufsize)

    async def shutdown(self, how: int, /) -> None:
        with contextlib.ExitStack() as stack:
            socket: _socket.socket = self.__check_not_closed()
            did_shutdown_SHUT_WR: bool = False
            if how in {_socket.SHUT_RDWR, _socket.SHUT_WR}:
                stack.enter_context(self.__conflict_detection("send", abort_errno=None))
                did_shutdown_SHUT_WR = True

            socket.shutdown(how)
            if did_shutdown_SHUT_WR:
                self.__shutdown_write = True

        # Yield outside the conflict detections scopes
        await asyncio.sleep(0)

    @contextlib.contextmanager
    def __conflict_detection(self, task_id: _SocketTaskId, *, abort_errno: int | None) -> Iterator[_socket.socket]:
        socket = self.__check_not_closed()

        if task_id in self.__waiters:
            raise _error_from_errno(_errno.EBUSY)

        task = TaskUtils.current_asyncio_task(self.__loop)

        with contextlib.ExitStack() as stack:
            self.__tasks.add(task)
            stack.callback(self.__tasks.discard, task)

            waiter: asyncio.Future[None] = self.__loop.create_future()
            stack.callback(waiter.set_result, None)
            self.__waiters[task_id] = waiter
            stack.callback(self.__waiters.pop, task_id)
            del waiter

            if abort_errno is None:
                # Short circuit.
                del task
                yield socket
                return

            task_cancelling = task.cancelling()

            try:
                yield socket
            except asyncio.CancelledError:
                if self.__socket is not None:
                    raise
                if task.cancelling() <= task_cancelling or task.uncancel() > task_cancelling:
                    raise
                raise _error_from_errno(abort_errno) from None
            finally:
                del task

    def __check_not_closed(self) -> _socket.socket:
        if (socket := self.__socket) is None:
            raise _error_from_errno(_errno.ENOTSOCK)
        return socket

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        return self.__loop

    @property
    def socket(self) -> asyncio.trsock.TransportSocket:
        return self.__trsock

    @property
    def did_shutdown_SHUT_WR(self) -> bool:
        return self.__shutdown_write
