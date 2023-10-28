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

__all__ = ["ListenerSocketAdapter", "connect_accepted_socket"]

import asyncio
import asyncio.streams
import dataclasses
import errno as _errno
import logging
import os
import socket as _socket
from abc import abstractmethod
from collections.abc import Callable, Coroutine, Mapping
from typing import TYPE_CHECKING, Any, Generic, NoReturn, TypeVar, final

from easynetwork.lowlevel.api_async.transports import abc as transports
from easynetwork.lowlevel.constants import ACCEPT_CAPACITY_ERRNOS, ACCEPT_CAPACITY_ERROR_SLEEP_TIME, NOT_CONNECTED_SOCKET_ERRNOS
from easynetwork.lowlevel.socket import _get_socket_extra

from ..socket import AsyncSocket
from ..tasks import TaskUtils
from .socket import AsyncioTransportStreamSocketAdapter, RawStreamSocketAdapter

if TYPE_CHECKING:
    import asyncio.trsock
    import ssl as _ssl

    from easynetwork.lowlevel.api_async.backend.abc import TaskGroup as AbstractTaskGroup


_T_Stream = TypeVar("_T_Stream", bound=AsyncioTransportStreamSocketAdapter | RawStreamSocketAdapter)


async def connect_accepted_socket(
    loop: asyncio.AbstractEventLoop,
    sock: _socket.socket,
    *,
    limit: int = 65536,
    ssl: _ssl.SSLContext | None = None,
    ssl_handshake_timeout: float | None = None,
    ssl_shutdown_timeout: float | None = None,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    reader = asyncio.streams.StreamReader(limit=limit, loop=loop)
    protocol = asyncio.streams.StreamReaderProtocol(reader, loop=loop)
    transport, _ = await loop.connect_accepted_socket(
        lambda: protocol,
        sock,
        ssl=ssl,
        ssl_handshake_timeout=ssl_handshake_timeout,
        ssl_shutdown_timeout=ssl_shutdown_timeout,
    )
    writer = asyncio.streams.StreamWriter(transport, protocol, reader, loop)
    return reader, writer


class ListenerSocketAdapter(transports.AsyncListener[_T_Stream]):
    __slots__ = ("__socket", "__accepted_socket_factory")

    def __init__(
        self,
        socket: _socket.socket,
        loop: asyncio.AbstractEventLoop,
        accepted_socket_factory: AbstractAcceptedSocketFactory[_T_Stream],
    ) -> None:
        super().__init__()

        if socket.type != _socket.SOCK_STREAM:
            raise ValueError("A 'SOCK_STREAM' socket is expected")

        self.__socket: AsyncSocket = AsyncSocket(socket, loop)
        self.__accepted_socket_factory = accepted_socket_factory

    def is_closing(self) -> bool:
        return self.__socket.is_closing()

    async def aclose(self) -> None:
        return await self.__socket.aclose()

    async def serve(self, handler: Callable[[_T_Stream], Coroutine[Any, Any, None]], task_group: AbstractTaskGroup) -> NoReturn:
        connect = self.__accepted_socket_factory.connect
        loop = self.__socket.loop
        logger = logging.getLogger(__name__)

        async def client_task(client_socket: _socket.socket) -> None:
            try:
                stream = await connect(client_socket, loop)
            except asyncio.CancelledError:
                client_socket.close()
                raise
            except BaseException as exc:
                client_socket.close()

                if isinstance(exc, OSError) and exc.errno in NOT_CONNECTED_SOCKET_ERRNOS:
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
                await handler(stream)

        while True:
            try:
                client_socket = await self.__socket.accept()
            except OSError as exc:
                if exc.errno in ACCEPT_CAPACITY_ERRNOS:
                    logger.error(
                        "accept returned %s (%s); retrying in %s seconds",
                        _errno.errorcode[exc.errno],
                        os.strerror(exc.errno),
                        ACCEPT_CAPACITY_ERROR_SLEEP_TIME,
                        exc_info=exc,
                    )
                    await asyncio.sleep(ACCEPT_CAPACITY_ERROR_SLEEP_TIME)
                else:
                    raise
            else:
                task_group.start_soon(client_task, client_socket)
                del client_socket
                await TaskUtils.cancel_shielded_coro_yield()

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        socket = self.__socket.socket
        return _get_socket_extra(socket, wrap_in_proxy=False)


class AbstractAcceptedSocketFactory(Generic[_T_Stream]):
    __slots__ = ()

    @abstractmethod
    def log_connection_error(self, logger: logging.Logger, exc: BaseException) -> None:
        raise NotImplementedError

    @abstractmethod
    async def connect(self, socket: _socket.socket, loop: asyncio.AbstractEventLoop) -> _T_Stream:
        raise NotImplementedError


@final
@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class AcceptedSocketFactory(AbstractAcceptedSocketFactory[AsyncioTransportStreamSocketAdapter | RawStreamSocketAdapter]):
    use_asyncio_transport: bool

    def log_connection_error(self, logger: logging.Logger, exc: BaseException) -> None:
        logger.error("Error in client task", exc_info=exc)

    async def connect(
        self,
        socket: _socket.socket,
        loop: asyncio.AbstractEventLoop,
    ) -> AsyncioTransportStreamSocketAdapter | RawStreamSocketAdapter:
        if not self.use_asyncio_transport:
            return RawStreamSocketAdapter(socket, loop)

        reader, writer = await connect_accepted_socket(loop, socket)
        return AsyncioTransportStreamSocketAdapter(reader, writer)


@final
@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class AcceptedSSLSocketFactory(AbstractAcceptedSocketFactory[AsyncioTransportStreamSocketAdapter]):
    ssl_context: _ssl.SSLContext
    ssl_handshake_timeout: float
    ssl_shutdown_timeout: float

    def log_connection_error(self, logger: logging.Logger, exc: BaseException) -> None:
        logger.error("Error in client task (during TLS handshake)", exc_info=exc)

    async def connect(
        self,
        socket: _socket.socket,
        loop: asyncio.AbstractEventLoop,
    ) -> AsyncioTransportStreamSocketAdapter:
        reader, writer = await connect_accepted_socket(
            loop,
            socket,
            ssl=self.ssl_context,
            ssl_handshake_timeout=self.ssl_handshake_timeout,
            ssl_shutdown_timeout=self.ssl_shutdown_timeout,
        )
        return AsyncioTransportStreamSocketAdapter(reader, writer)
