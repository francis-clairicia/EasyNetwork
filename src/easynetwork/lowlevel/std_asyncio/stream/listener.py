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

__all__ = [
    "AbstractAcceptedSocketFactory",
    "AcceptedSocketFactory",
    "ListenerSocketAdapter",
]

import asyncio
import asyncio.trsock
import contextlib
import dataclasses
import errno as _errno
import logging
import os
import socket as _socket
import warnings
from abc import abstractmethod
from collections.abc import Callable, Coroutine, Mapping
from typing import TYPE_CHECKING, Any, Generic, NoReturn, TypeVar, final

from ... import _utils, constants, socket as socket_tools
from ...api_async.transports import abc as transports
from ..tasks import CancelScope, TaskGroup as AsyncIOTaskGroup, TaskUtils
from .socket import AsyncioTransportStreamSocketAdapter, StreamReaderBufferedProtocol

if TYPE_CHECKING:
    from ...api_async.backend.abc import TaskGroup as AbstractTaskGroup
    from ..backend import AsyncIOBackend


_T_Stream = TypeVar("_T_Stream", bound=transports.AsyncStreamTransport)


class ListenerSocketAdapter(transports.AsyncListener[_T_Stream]):
    __slots__ = (
        "__backend",
        "__socket",
        "__trsock",
        "__accepted_socket_factory",
        "__accept_scope",
        "__serve_guard",
    )

    def __init__(
        self,
        backend: AsyncIOBackend,
        socket: _socket.socket,
        accepted_socket_factory: AbstractAcceptedSocketFactory[_T_Stream],
    ) -> None:
        super().__init__()

        if socket.type != _socket.SOCK_STREAM:
            raise ValueError("A 'SOCK_STREAM' socket is expected")

        _utils.check_socket_no_ssl(socket)
        socket.setblocking(False)

        self.__socket: _socket.socket | None = socket
        self.__trsock: asyncio.trsock.TransportSocket = asyncio.trsock.TransportSocket(socket)
        self.__backend: AsyncIOBackend = backend
        self.__accepted_socket_factory = accepted_socket_factory
        self.__accept_scope: CancelScope | None = None
        self.__serve_guard: _utils.ResourceGuard = _utils.ResourceGuard(f"{self.__class__.__name__}.serve() awaited twice.")

    def __del__(self, *, _warn: _utils.WarnCallback = warnings.warn) -> None:
        try:
            socket: _socket.socket | None = self.__socket
        except AttributeError:
            return
        if socket is not None:
            _warn(f"unclosed listener {self!r}", ResourceWarning, source=self)
            socket.close()

    def is_closing(self) -> bool:
        return self.__socket is None

    async def aclose(self) -> None:
        socket = self.__socket
        if socket is None:
            return
        with contextlib.closing(socket):
            self.__socket = None
            if self.__accept_scope is not None:
                self.__accept_scope.cancel()
                await TaskUtils.coro_yield()

    async def serve(
        self,
        handler: Callable[[_T_Stream], Coroutine[Any, Any, None]],
        task_group: AbstractTaskGroup | None = None,
    ) -> NoReturn:
        connect = self.__accepted_socket_factory.connect
        logger = logging.getLogger(__name__)

        async def client_connection_task(client_socket: _socket.socket, task_group: AbstractTaskGroup) -> None:
            try:
                stream = await connect(self.__backend, client_socket)
            except asyncio.CancelledError:
                client_socket.close()
                raise
            except BaseException as exc:
                client_socket.close()

                if isinstance(exc, OSError) and exc.errno in constants.NOT_CONNECTED_SOCKET_ERRNOS:
                    # The remote host closed the connection before starting the task.
                    # See this test for details:
                    # test____serve_forever____accept_client____client_sent_RST_packet_right_after_accept
                    logger.warning("A client connection was interrupted just after listener.accept()")
                else:
                    self.__accepted_socket_factory.log_connection_error(logger, exc)

                # Only reraise base exceptions
                if not isinstance(exc, Exception):
                    raise
            else:
                task_group.start_soon(handler, stream)

        async with contextlib.AsyncExitStack() as stack:
            stack.enter_context(self.__serve_guard)
            if task_group is None:
                task_group = await stack.enter_async_context(AsyncIOTaskGroup())
            while True:
                client_socket: _socket.socket | None = None
                try:
                    client_socket = await self.raw_accept()
                except OSError as exc:
                    if exc.errno in constants.ACCEPT_CAPACITY_ERRNOS:
                        logger.error(
                            "accept returned %s (%s); retrying in %s seconds",
                            _errno.errorcode[exc.errno],
                            os.strerror(exc.errno),
                            constants.ACCEPT_CAPACITY_ERROR_SLEEP_TIME,
                            exc_info=exc,
                        )
                        await asyncio.sleep(constants.ACCEPT_CAPACITY_ERROR_SLEEP_TIME)
                    else:
                        raise
                else:
                    task_group.start_soon(client_connection_task, client_socket, task_group)

        raise AssertionError("Expected code to be unreachable.")

    async def raw_accept(self) -> _socket.socket:
        if self.__accept_scope is not None:
            raise _utils.error_from_errno(_errno.EBUSY)
        listener_sock = self.__socket
        if listener_sock is None:
            raise _utils.error_from_errno(_errno.EBADF)
        client_sock: _socket.socket | None = None
        loop = asyncio.get_running_loop()

        with CancelScope() as self.__accept_scope:
            try:
                client_sock, _ = await loop.sock_accept(listener_sock)
            finally:
                self.__accept_scope = None

        if client_sock is None:
            raise _utils.error_from_errno(_errno.EBADF)
        return client_sock

    def backend(self) -> AsyncIOBackend:
        return self.__backend

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return socket_tools._get_socket_extra(self.__trsock, wrap_in_proxy=False)


class AbstractAcceptedSocketFactory(Generic[_T_Stream]):
    __slots__ = ()

    @abstractmethod
    def log_connection_error(self, logger: logging.Logger, exc: BaseException) -> None:
        raise NotImplementedError

    @abstractmethod
    async def connect(self, backend: AsyncIOBackend, socket: _socket.socket) -> _T_Stream:
        raise NotImplementedError


@final
@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class AcceptedSocketFactory(AbstractAcceptedSocketFactory[AsyncioTransportStreamSocketAdapter]):
    def log_connection_error(self, logger: logging.Logger, exc: BaseException) -> None:
        logger.error("Error in client task", exc_info=exc)

    async def connect(
        self,
        backend: AsyncIOBackend,
        socket: _socket.socket,
    ) -> AsyncioTransportStreamSocketAdapter:
        loop = asyncio.get_running_loop()
        transport, protocol = await loop.connect_accepted_socket(
            _utils.make_callback(StreamReaderBufferedProtocol, loop=loop),
            socket,
        )
        return AsyncioTransportStreamSocketAdapter(backend, transport, protocol)
