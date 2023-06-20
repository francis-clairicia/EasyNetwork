# -*- coding: utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
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
from typing import TYPE_CHECKING, Any, Iterator, Literal, Self, TypeAlias
from weakref import WeakSet

from easynetwork.tools._utils import check_socket_no_ssl as _check_socket_no_ssl, error_from_errno as _error_from_errno

if TYPE_CHECKING:
    import socket as _socket
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
        "__closing",
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
        self.__closing: bool = False

    def __del__(self) -> None:  # pragma: no cover
        self.__closing = True
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
        return self.__socket is None or self.__closing

    async def aclose(self) -> None:
        socket, self.__socket = self.__socket, None
        self.__closing = True

        if socket is None:
            await asyncio.sleep(0)
            return
        try:
            for task in list(self.__tasks):
                task.cancel()
                del task
            futures_to_wait_for_completion: set[asyncio.Future[None]] = set(self.__waiters.values())
            if futures_to_wait_for_completion:
                await asyncio.wait(futures_to_wait_for_completion, return_when=asyncio.ALL_COMPLETED)
        finally:
            socket.close()
            await asyncio.sleep(0)

    async def accept(self) -> tuple[_socket.socket, _socket._RetAddress]:
        with self.__conflict_detection("accept") as socket:
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

    @contextlib.contextmanager
    def __conflict_detection(self, task_id: _SocketTaskId, *, abort_errno: int | None = None) -> Iterator[_socket.socket]:
        if (socket := self.__socket if not self.__closing else None) is None:
            raise _error_from_errno(_errno.ENOTSOCK)

        if task_id in self.__waiters:
            raise _error_from_errno(_errno.EBUSY)

        if abort_errno is None:
            abort_errno = _errno.EINTR

        task = asyncio.current_task()
        if task is None:  # pragma: no cover
            raise RuntimeError("This function should be called within a task.")
        assert task.get_loop() is self.__loop, "coroutine will not be executed with the bound event loop"

        with contextlib.ExitStack() as stack:
            self.__tasks.add(task)
            stack.callback(self.__tasks.discard, task)

            waiter: asyncio.Future[None] = self.__loop.create_future()
            stack.callback(waiter.set_result, None)
            self.__waiters[task_id] = waiter
            stack.callback(self.__waiters.pop, task_id)
            del waiter

            try:
                yield socket
            except asyncio.CancelledError:
                if self.__socket is not None or task.uncancel() > 0:
                    raise
                raise _error_from_errno(abort_errno) from None
            finally:
                del task

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        return self.__loop

    @property
    def socket(self) -> asyncio.trsock.TransportSocket:
        return self.__trsock
