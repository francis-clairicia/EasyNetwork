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

__all__ = ["TrioDatagramListenerSocketAdapter"]

import contextlib
import logging
import socket as _socket
import warnings
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, NoReturn, final

import trio

from ..... import _utils, socket as socket_tools
from ....transports.abc import AsyncDatagramListener
from ...abc import AsyncBackend, ILock, TaskGroup
from .._trio_utils import FastFIFOLock, close_socket_and_notify, retry_socket_method as _retry_socket_method

if TYPE_CHECKING:
    from socket import _Address, _RetAddress


@final
class TrioDatagramListenerSocketAdapter(AsyncDatagramListener["_RetAddress"]):
    __slots__ = (
        "__backend",
        "__listener",
        "__serve_guard",
        "__send_lock",
        "__extra_attributes",
        "__wait_readable",
        "__wait_writable",
    )

    from .....constants import MAX_DATAGRAM_BUFSIZE

    def __init__(self, backend: AsyncBackend, sock: _socket.socket) -> None:
        super().__init__()

        if sock.type != _socket.SOCK_DGRAM:
            raise ValueError("A 'SOCK_DGRAM' socket is expected")

        sock.setblocking(False)

        from trio.lowlevel import wait_readable, wait_writable

        self.__backend: AsyncBackend = backend
        self.__listener: _socket.socket = sock
        self.__serve_guard: _utils.ResourceGuard = _utils.ResourceGuard(f"{self.__class__.__name__}.serve() awaited twice.")
        self.__send_lock: ILock = FastFIFOLock()
        self.__extra_attributes = MappingProxyType(socket_tools._get_socket_extra(sock))

        self.__wait_readable: Callable[[_socket.socket], Awaitable[None]] = wait_readable
        self.__wait_writable: Callable[[_socket.socket], Awaitable[None]] = wait_writable

    def __del__(self, *, _warn: _utils.WarnCallback = warnings.warn) -> None:
        try:
            listener = self.__listener
        except AttributeError:
            listener = None
        if listener is not None and listener.fileno() >= 0:
            _warn(f"unclosed listener {self!r}", ResourceWarning, source=self)
            listener.close()

    async def aclose(self) -> None:
        try:
            async with self.__send_lock:
                # Only waits for the lock
                # If we have been cancelled, forcefully closes the socket.
                pass
        finally:
            close_socket_and_notify(self.__listener)
        await trio.lowlevel.checkpoint()

    def is_closing(self) -> bool:
        return self.__listener.fileno() < 0

    async def serve(
        self,
        handler: Callable[[bytes, _RetAddress], Coroutine[Any, Any, None]],
        task_group: TaskGroup | None = None,
    ) -> NoReturn:
        async with contextlib.AsyncExitStack() as stack:
            stack.enter_context(self.__serve_guard)
            if task_group is None:
                task_group = await stack.enter_async_context(self.__backend.create_task_group())

            MAX_DATAGRAM_BUFSIZE = self.MAX_DATAGRAM_BUFSIZE
            listener = self.__listener
            wait_readable = self.__wait_readable
            logger = logging.getLogger(__name__)

            while True:
                try:
                    datagram, client_address = await _retry_socket_method(
                        wait_readable,
                        listener,
                        lambda: listener.recvfrom(MAX_DATAGRAM_BUFSIZE),
                        always_yield=True,
                    )
                except OSError as exc:
                    logger.warning(
                        "Unrelated error occurred on datagram reception: %s: %s",
                        type(exc).__name__,
                        exc,
                        exc_info=exc,
                    )
                    continue

                task_group.start_soon(handler, datagram, client_address)
                # Always drop references on loop end
                del datagram, client_address

        raise AssertionError("Expected code to be unreachable.")

    async def send_to(self, data: bytes | bytearray | memoryview, address: _Address) -> None:
        async with self.__send_lock:
            await _retry_socket_method(
                self.__wait_writable,
                (listener := self.__listener),
                lambda: listener.sendto(data, address),
                always_yield=False,
                checkpoint_if_cancelled=False,  # <- Already checked by send_lock
            )

    def backend(self) -> AsyncBackend:
        return self.__backend

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__extra_attributes
