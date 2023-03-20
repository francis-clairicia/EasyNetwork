# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""asyncio engine for easynetwork.async
"""

from __future__ import annotations

__all__ = [
    "TransportDatagramSocket",
    "TransportDatagramSocketProtocol",
]

import asyncio
import collections
import errno as _errno
import socket as _socket
from typing import TYPE_CHECKING, final

from easynetwork.asyncio.backend import AbstractDatagramSocketAdapter
from easynetwork.tools._utils import error_from_errno as _error_from_errno
from easynetwork.tools.socket import SocketProxy

if TYPE_CHECKING:
    from socket import _Address, _RetAddress

    from _typeshed import ReadableBuffer

    from . import AsyncIOBackend


@final
class TransportDatagramSocket(AbstractDatagramSocketAdapter):
    __slots__ = (
        "__backend",
        "__recv_queue",
        "__exception_queue",
        "__transport",
        "__protocol",
        "__proxy",
    )

    def __init__(
        self,
        backend: AsyncIOBackend,
        transport: asyncio.DatagramTransport,
        protocol: TransportDatagramSocketProtocol,
        *,
        recv_queue: asyncio.Queue[tuple[bytes | None, _RetAddress | None]],
        exception_queue: asyncio.Queue[Exception],
    ) -> None:
        super().__init__()
        self.__backend: AsyncIOBackend = backend
        self.__recv_queue: asyncio.Queue[tuple[bytes | None, _RetAddress | None]] = recv_queue
        self.__exception_queue: asyncio.Queue[Exception] = exception_queue
        self.__transport: asyncio.DatagramTransport = transport
        self.__protocol: TransportDatagramSocketProtocol = protocol

        socket: _socket.socket | None = transport.get_extra_info("socket")
        assert isinstance(socket, _socket.socket), "transport must be a socket transport"

        self.__proxy: SocketProxy = SocketProxy(socket)

    def __del__(self) -> None:  # pragma: no cover
        try:
            transport = self.__transport
        except AttributeError:
            return
        transport.close()

    async def close(self) -> None:
        self.__transport.close()
        await self.__protocol._get_close_waiter()

    def is_closing(self) -> bool:
        return self.__transport.is_closing()

    async def recvfrom(self) -> tuple[bytes, _RetAddress]:
        if self.__transport.is_closing() or self.__protocol._is_connection_lost():
            raise _error_from_errno(_errno.ECONNABORTED)
        self.__check_exceptions()
        data, address = await self.__recv_queue.get()
        if data is None or address is None:
            self.__check_exceptions()  # Woken up because an error occurred ?
            assert self.__protocol._is_connection_lost()
            raise _error_from_errno(_errno.ECONNABORTED)  # Connection lost otherwise
        return data, address

    async def sendto(self, data: ReadableBuffer, address: _Address | None = None, /) -> None:
        if self.__transport.is_closing() or self.__protocol._is_connection_lost():
            raise _error_from_errno(_errno.ECONNREFUSED)
        self.__check_exceptions()
        with memoryview(data) as buffer:
            self.__transport.sendto(buffer, address)
        await self.__protocol._drain_helper()

    def proxy(self) -> SocketProxy:
        return self.__proxy

    def get_backend(self) -> AsyncIOBackend:
        return self.__backend

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


class TransportDatagramSocketProtocol(asyncio.DatagramProtocol):
    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop | None = None,
        recv_queue: asyncio.Queue[tuple[bytes | None, _RetAddress | None]],
        exception_queue: asyncio.Queue[Exception],
    ) -> None:
        super().__init__()
        if loop is None:
            loop = asyncio.get_running_loop()
        self.__loop: asyncio.AbstractEventLoop = loop
        self.__recv_queue: asyncio.Queue[tuple[bytes | None, _RetAddress | None]] = recv_queue
        self.__exception_queue: asyncio.Queue[Exception] = exception_queue
        self.__transport: asyncio.BaseTransport | None = None
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

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        assert self.__transport is None, "Transport already set"
        self.__transport = transport
        self.__connection_lost = False

    def connection_lost(self, exc: Exception | None) -> None:
        self.__connection_lost = True

        if not self.__closed.done():
            if exc is None:
                self.__closed.set_result(None)
            else:
                self.__closed.set_exception(exc)

        if self.__write_paused:
            for waiter in self.__drain_waiters:
                if not waiter.done():
                    if exc is None:
                        waiter.set_result(None)
                    else:
                        waiter.set_exception(exc)

        self.__recv_queue.put_nowait((None, None))  # Wake up socket
        if exc is not None:
            self.__exception_queue.put_nowait(exc)

        if self.__transport is not None:
            self.__transport.close()
            self.__transport = None

        super().connection_lost(exc)

    def datagram_received(self, data: bytes, addr: _RetAddress) -> None:
        if self.__transport is not None:
            self.__recv_queue.put_nowait((data, addr))

    def error_received(self, exc: Exception) -> None:
        if self.__transport is not None:
            self.__exception_queue.put_nowait(exc)
            self.__recv_queue.put_nowait((None, None))  # Wake up socket

    def pause_writing(self) -> None:
        assert not self.__write_paused
        self.__write_paused = True
        if self.__loop.get_debug():
            from asyncio.log import logger

            logger.debug("%r pauses writing", self)

        super().pause_writing()

    def resume_writing(self) -> None:
        assert self.__write_paused
        self.__write_paused = False
        if self.__loop.get_debug():
            from asyncio.log import logger

            logger.debug("%r resumes writing", self)

        for waiter in self.__drain_waiters:
            if not waiter.done():
                waiter.set_result(None)

        super().resume_writing()

    def _is_connection_lost(self) -> bool:
        return self.__connection_lost

    async def _drain_helper(self) -> None:
        if self.__connection_lost:
            raise _error_from_errno(_errno.ECONNABORTED)
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
