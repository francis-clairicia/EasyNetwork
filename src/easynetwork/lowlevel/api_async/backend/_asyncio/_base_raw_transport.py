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

__all__ = ["BaseRawSocketTransport"]

import asyncio
import asyncio.trsock
import contextlib
import errno as _errno
import socket as _socket
import warnings
from collections.abc import Awaitable, Callable, Iterator, Mapping
from types import MappingProxyType
from typing import Any, Literal, TypeVar, overload

from .....exceptions import BusyResourceError
from .... import _utils, socket as socket_tools
from ...transports.abc import AsyncBaseTransport
from ..abc import AsyncBackend, CancelScope
from . import _asyncio_utils
from .tasks import TaskUtils

_T_Data = TypeVar("_T_Data")
_T_Result = TypeVar("_T_Result")


class BaseRawSocketTransport(AsyncBaseTransport):
    __slots__ = (
        "__backend",
        "__socket",
        "__extra_attributes",
        "__read_scope",
        "__write_scope",
    )

    def __init__(
        self,
        backend: AsyncBackend,
        socket: _socket.socket,
    ) -> None:
        _utils.check_socket_no_ssl(socket)
        socket.setblocking(False)
        trsock: asyncio.trsock.TransportSocket = asyncio.trsock.TransportSocket(socket)

        self.__socket: _socket.socket | None = socket
        self.__backend: AsyncBackend = backend
        self.__extra_attributes = MappingProxyType(socket_tools._get_socket_extra(trsock, wrap_in_proxy=False))

        self.__read_scope: CancelScope | None = None
        self.__write_scope: tuple[CancelScope, asyncio.Future[None]] | None = None

    def __del__(self, *, _warn: _utils.WarnCallback = warnings.warn) -> None:
        try:
            socket: _socket.socket | None = self.__socket
        except AttributeError:
            return
        if socket is not None and socket.fileno() >= 0:
            _warn(f"unclosed transport {self!r}", ResourceWarning, source=self)
            socket.close()

    def is_closing(self) -> bool:
        return (s := self.__socket) is None or s.fileno() < 0

    async def aclose(self) -> None:
        socket = self.__socket
        if socket is None:
            return
        with contextlib.closing(socket):
            self.__socket = None
            if self.__read_scope is not None:
                self.__read_scope.cancel()
                await TaskUtils.coro_yield()
            if self.__write_scope is not None:
                write_scope, write_fut = self.__write_scope
                try:
                    await asyncio.shield(write_fut)
                except self.__backend.get_cancelled_exc_class():
                    write_scope.cancel()
                    raise

    async def _sock_recv(
        self,
        requester: str,
        *,
        recv: Callable[[_socket.socket], _T_Result],
        try_async_recv: Callable[[asyncio.AbstractEventLoop, _socket.socket], Awaitable[_T_Result]] | None = None,
    ) -> _T_Result:
        with self._read_task_context(requester) as sock:
            loop = asyncio.get_running_loop()
            if try_async_recv is not None:
                try:
                    return await try_async_recv(loop, sock)
                except NotImplementedError:
                    pass

            while True:
                try:
                    return recv(sock)
                except (BlockingIOError, InterruptedError):
                    pass
                await _asyncio_utils.wait_until_readable(sock, loop)

    async def _sock_send(
        self,
        requester: str,
        *,
        send: Callable[[_socket.socket], _T_Result],
        try_async_send: Callable[[asyncio.AbstractEventLoop, _socket.socket], Awaitable[_T_Result]] | None = None,
    ) -> _T_Result:
        loop = asyncio.get_running_loop()
        with self._write_task_context(requester, loop=loop) as sock:
            if try_async_send is not None:
                try:
                    return await try_async_send(loop, sock)
                except NotImplementedError:
                    pass

            while True:
                try:
                    return send(sock)
                except (BlockingIOError, InterruptedError):
                    pass
                await _asyncio_utils.wait_until_writable(sock, loop)

    async def _sock_send_all(
        self,
        requester: str,
        *,
        data: _T_Data,
        send: Callable[[_socket.socket, _T_Data], _T_Result],
        send_success: Callable[[_T_Result, _T_Data], _T_Data],
        retry_send: Callable[[_T_Data], object],
        try_async_send: Callable[[asyncio.AbstractEventLoop, _socket.socket, _T_Data], Awaitable[None]] | None = None,
    ) -> None:
        try:
            loop = asyncio.get_running_loop()
            with self._write_task_context(requester, loop=loop) as sock:
                if try_async_send is not None:
                    try:
                        return await try_async_send(loop, sock, data)
                    except NotImplementedError:
                        pass

                while True:
                    try:
                        result = send(sock, data)
                    except (BlockingIOError, InterruptedError):
                        pass
                    else:
                        data = send_success(result, data)
                        if retry_send(data):
                            continue
                        return
                    await _asyncio_utils.wait_until_writable(sock, loop)
        finally:
            del data

    @contextlib.contextmanager
    def _read_task_context(self, requester: str, /) -> Iterator[_socket.socket]:
        if self.__read_scope is not None:
            raise BusyResourceError(f"{requester}() called while another coroutine is already waiting for incoming data")
        sock = self.__socket
        if sock is None:
            raise _utils.error_from_errno(_errno.EBADF)
        with self.__backend.open_cancel_scope() as scope:
            self.__read_scope = scope
            try:
                yield sock
            finally:
                self.__read_scope = None
        if scope.cancelled_caught():
            # aclose() cancelled the scope
            raise _utils.error_from_errno(_errno.EBADF)

    @overload
    @contextlib.contextmanager
    def _write_task_context(
        self,
        requester: str,
        /,
        *,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> Iterator[_socket.socket]: ...

    @overload
    @contextlib.contextmanager
    def _write_task_context(
        self,
        requester: str,
        /,
        *,
        loop: asyncio.AbstractEventLoop | None = None,
        accept_closed_sockets: Literal[True],
    ) -> Iterator[_socket.socket | None]: ...

    @contextlib.contextmanager
    def _write_task_context(
        self,
        requester: str,
        /,
        *,
        loop: asyncio.AbstractEventLoop | None = None,
        accept_closed_sockets: bool = False,
    ) -> Iterator[_socket.socket | None]:
        if self.__write_scope is not None:
            raise BusyResourceError(f"{requester}() called while another coroutine is already sending data")
        sock = self.__socket
        if sock is None and not accept_closed_sockets:
            raise _utils.error_from_errno(_errno.EBADF)

        if loop is None:
            loop = asyncio.get_running_loop()
        with self.__backend.open_cancel_scope() as scope:
            f = loop.create_future()
            self.__write_scope = (scope, f)
            try:
                try:
                    yield sock
                finally:
                    f.set_result(None)
            finally:
                self.__write_scope = None
        if scope.cancelled_caught():
            # aclose() cancelled the scope
            raise _utils.error_from_errno(_errno.EBADF)

    def backend(self) -> AsyncBackend:
        return self.__backend

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__extra_attributes
