# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""asyncio engine for easynetwork.async
"""

from __future__ import annotations

__all__ = ["ListenerSocketAdapter"]

import collections
from typing import TYPE_CHECKING, Any, final

from easynetwork.api_async.backend.abc import AbstractAsyncListenerSocketAdapter, AbstractAsyncStreamSocketAdapter
from easynetwork.tools._utils import error_from_errno as _error_from_errno
from easynetwork.tools.socket import SocketProxy

if TYPE_CHECKING:
    import asyncio
    import socket as _socket


@final
class ListenerSocketAdapter(AbstractAsyncListenerSocketAdapter):
    __slots__ = (
        "__socket",
        "__loop",
        "__proxy",
        "__tasks",
        "__closed",
    )

    def __init__(self, socket: _socket.socket, *, loop: asyncio.AbstractEventLoop | None = None) -> None:
        super().__init__()
        if loop is None:
            import asyncio

            loop = asyncio.get_running_loop()

        self.__socket: _socket.socket = socket
        self.__loop: asyncio.AbstractEventLoop = loop
        self.__proxy: SocketProxy = SocketProxy(socket)
        self.__tasks: collections.deque[asyncio.Task[Any]] = collections.deque()
        self.__closed: bool = False

    def is_closing(self) -> bool:
        return self.__closed

    async def close(self) -> None:
        if self.__closed:
            return

        self.__closed = True
        for accept_task in self.__tasks:
            if not accept_task.done():
                accept_task.cancel()

        self.__socket.close()

    async def abort(self) -> None:
        return await self.close()

    async def accept(self) -> tuple[AbstractAsyncStreamSocketAdapter, tuple[Any, ...]]:
        if self.__closed:
            import errno

            raise _error_from_errno(errno.EBADFD)

        task = self.__loop.create_task(self.__loop.sock_accept(self.__socket))
        self.__tasks.append(task)
        try:
            client_socket, client_address = await task
        finally:
            self.__tasks.remove(task)
            del task

        client_socket_adapter = await self._make_socket_adapter(client_socket)
        return client_socket_adapter, client_address

    async def _make_socket_adapter(self, client_socket: _socket.socket) -> AbstractAsyncStreamSocketAdapter:
        from asyncio.streams import StreamReader, StreamReaderProtocol, StreamWriter

        from easynetwork.tools.socket import MAX_STREAM_BUFSIZE

        from .socket import StreamSocketAdapter

        client_reader = StreamReader(MAX_STREAM_BUFSIZE, self.__loop)
        client_protocol = StreamReaderProtocol(client_reader, loop=self.__loop)
        client_transport, client_protocol = await self.__loop.connect_accepted_socket(lambda: client_protocol, client_socket)
        client_writer = StreamWriter(client_transport, client_protocol, client_reader, self.__loop)
        return StreamSocketAdapter(client_reader, client_writer)

    def getsockname(self) -> tuple[Any, ...]:
        return self.__socket.getsockname()

    def proxy(self) -> SocketProxy:
        return self.__proxy
