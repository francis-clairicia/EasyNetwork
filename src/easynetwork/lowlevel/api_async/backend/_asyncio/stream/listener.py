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

__all__ = [
    "AbstractAcceptedSocketFactory",
    "AcceptedSocketFactory",
    "ListenerSocketAdapter",
]

import asyncio
import asyncio.trsock
import collections
import contextlib
import dataclasses
import errno as _errno
import logging
import os
import socket as _socket
import warnings
from abc import abstractmethod
from collections.abc import Callable, Coroutine, Mapping
from types import MappingProxyType
from typing import Any, Generic, NoReturn, TypeVar, final

from ......exceptions import UnsupportedOperation
from ..... import _utils, constants, socket as socket_tools
from ....transports.abc import AsyncListener, AsyncStreamTransport
from ...abc import AsyncBackend, CancelScope, TaskGroup
from ..tasks import TaskUtils
from .socket import AsyncioTransportStreamSocketAdapter, StreamReaderBufferedProtocol

_T_Stream = TypeVar("_T_Stream", bound=AsyncStreamTransport)


class ListenerSocketAdapter(AsyncListener[_T_Stream]):
    __slots__ = (
        "__backend",
        "__socket",
        "__accepted_socket_factory",
        "__accept_scope",
        "__serve_guard",
        "__serve_backlog",
        "__extra_attributes",
    )

    def __init__(
        self,
        backend: AsyncBackend,
        socket: _socket.socket,
        accepted_socket_factory: AbstractAcceptedSocketFactory[_T_Stream],
        *,
        backlog: int,
    ) -> None:
        super().__init__()

        if socket.type != _socket.SOCK_STREAM:
            raise ValueError("A 'SOCK_STREAM' socket is expected")
        if backlog < 1:
            raise ValueError("backlog should be strictly positive")

        _utils.check_socket_no_ssl(socket)
        socket.setblocking(False)
        trsock: asyncio.trsock.TransportSocket = asyncio.trsock.TransportSocket(socket)

        self.__socket: _socket.socket | None = socket
        self.__backend: AsyncBackend = backend
        self.__accepted_socket_factory = accepted_socket_factory
        self.__accept_scope: CancelScope | None = None
        self.__serve_guard: _utils.ResourceGuard = _utils.ResourceGuard(f"{self.__class__.__name__}.serve() awaited twice.")
        self.__serve_backlog: int = backlog

        self.__extra_attributes = MappingProxyType(socket_tools._get_socket_extra(trsock, wrap_in_proxy=False))

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
        task_group: TaskGroup | None = None,
    ) -> NoReturn:
        connect = self.__accepted_socket_factory.connect
        logger = logging.getLogger(__name__)

        async with self.__backend.create_task_group() if task_group is None else contextlib.nullcontext(task_group) as task_group:

            async def client_connection_task(client_socket: _socket.socket) -> None:
                try:
                    stream = await connect(self.__backend, client_socket)
                except Exception as exc:
                    client_socket.close()
                    match exc:
                        case OSError(errno=exc_errno) if exc_errno in constants.NOT_CONNECTED_SOCKET_ERRNOS:
                            # The remote host closed the connection before starting the task.
                            # See this test for details:
                            # test____serve_forever____accept_client____client_sent_RST_packet_right_after_accept
                            pass
                        case _:
                            self.__accepted_socket_factory.log_connection_error(logger, exc)
                except BaseException:
                    # Only reraise base exceptions
                    client_socket.close()
                    raise
                else:
                    task_group.start_soon(handler, stream)

            await self._serve_raw(client_connection_task)

    async def _serve_raw(self, handler: Callable[[_socket.socket], Coroutine[Any, Any, None]]) -> NoReturn:
        with self.__serve_guard:
            listener_sock = self.__socket
            if listener_sock is None:
                raise _utils.error_from_errno(_errno.EBADF)

            async with self.__backend.create_task_group() as task_group:
                try:
                    with self.__backend.open_cancel_scope() as self.__accept_scope:
                        await self.__infinite_serve(
                            listener_sock,
                            lambda client_sock: task_group.start_soon(handler, client_sock),
                            self.__serve_backlog,
                        )
                except UnsupportedOperation:
                    pass
                else:
                    # accept_scope have been cancelled.
                    raise _utils.error_from_errno(_errno.EBADF)
                finally:
                    self.__accept_scope = None

                loop = asyncio.get_running_loop()
                logger = logging.getLogger(__name__)

                try:
                    with self.__backend.open_cancel_scope() as self.__accept_scope:
                        while True:
                            client_sock: _socket.socket | None = None
                            try:
                                client_sock, _ = await loop.sock_accept(listener_sock)
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
                                elif exc.errno not in constants.IGNORABLE_ACCEPT_ERRNOS:
                                    raise
                            else:
                                task_group.start_soon(handler, client_sock)
                    # accept_scope have been cancelled.
                    raise _utils.error_from_errno(_errno.EBADF)
                finally:
                    self.__accept_scope = None

    @classmethod
    def __infinite_serve(
        cls,
        listener_sock: _socket.socket,
        callback: Callable[[_socket.socket], Any],
        backlog: int,
    ) -> asyncio.Future[NoReturn]:
        loop = asyncio.get_running_loop()
        logger = logging.getLogger(__name__)
        delayed_retry_handles: collections.deque[asyncio.TimerHandle] = collections.deque()

        def on_fut_done(f: asyncio.Future[NoReturn]) -> None:
            loop.remove_reader(listener_sock)
            for handle in delayed_retry_handles:
                handle.cancel()
            delayed_retry_handles.clear()

        def listener_ready(f: asyncio.Future[NoReturn]) -> None:
            delayed_retry_handles.clear()
            if f.done():
                # I/O callbacks are always called before asyncio.Future done callbacks.
                return
            # This method is only called once for each event loop tick where the
            # listening socket has triggered an EVENT_READ. There may be multiple
            # connections waiting for an .accept() so it is called in a loop.
            # See https://github.com/python/cpython/issues/72093 for more details.
            for _ in range(backlog):
                client_sock: _socket.socket | None = None
                try:
                    client_sock, _ = listener_sock.accept()
                    client_sock.setblocking(False)
                except (BlockingIOError, InterruptedError):
                    return
                except OSError as exc:
                    if exc.errno in constants.ACCEPT_CAPACITY_ERRNOS:
                        logger.error(
                            "accept returned %s (%s); retrying in %s seconds",
                            _errno.errorcode[exc.errno],
                            os.strerror(exc.errno),
                            constants.ACCEPT_CAPACITY_ERROR_SLEEP_TIME,
                            exc_info=exc,
                        )
                        loop.remove_reader(listener_sock)
                        handle = loop.call_later(
                            constants.ACCEPT_CAPACITY_ERROR_SLEEP_TIME,
                            loop.add_reader,
                            listener_sock,
                            listener_ready,
                            f,
                        )
                        delayed_retry_handles.append(handle)
                    elif exc.errno not in constants.IGNORABLE_ACCEPT_ERRNOS:
                        # Unrelated OS error.
                        f.set_exception(exc)
                        loop.remove_reader(listener_sock)
                        # Break reference cycle with exception set.
                        del f
                    return
                except BaseException as exc:
                    f.set_exception(exc)
                    # Break reference cycle with exception set.
                    del f
                    return
                else:
                    callback(client_sock)

        f = loop.create_future()
        try:
            loop.add_reader(listener_sock, listener_ready, f)
        except NotImplementedError as exc:
            raise UnsupportedOperation from exc

        f.add_done_callback(on_fut_done)
        return f

    def backend(self) -> AsyncBackend:
        return self.__backend

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__extra_attributes


class AbstractAcceptedSocketFactory(Generic[_T_Stream]):
    __slots__ = ()

    @abstractmethod
    def log_connection_error(self, logger: logging.Logger, exc: BaseException) -> None:
        raise NotImplementedError

    @abstractmethod
    async def connect(self, backend: AsyncBackend, socket: _socket.socket) -> _T_Stream:
        raise NotImplementedError


@final
@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class AcceptedSocketFactory(AbstractAcceptedSocketFactory[AsyncioTransportStreamSocketAdapter]):
    def log_connection_error(self, logger: logging.Logger, exc: BaseException) -> None:
        logger.error("Error in client task", exc_info=exc)

    async def connect(
        self,
        backend: AsyncBackend,
        socket: _socket.socket,
    ) -> AsyncioTransportStreamSocketAdapter:
        loop = asyncio.get_running_loop()
        transport, protocol = await loop.connect_accepted_socket(
            _utils.make_callback(StreamReaderBufferedProtocol, loop=loop),
            socket,
        )
        return AsyncioTransportStreamSocketAdapter(backend, transport, protocol)
