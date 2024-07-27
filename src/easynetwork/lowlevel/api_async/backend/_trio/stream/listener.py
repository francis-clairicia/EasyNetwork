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
"""trio engine for easynetwork.api_async
"""

from __future__ import annotations

__all__ = ["TrioListenerSocketAdapter"]

import contextlib
import warnings
from collections.abc import Callable, Coroutine, Mapping
from typing import Any, NoReturn, final

import trio

from ..... import _utils, socket as socket_tools
from ....transports.abc import AsyncListener
from ...abc import AsyncBackend, TaskGroup
from .._trio_utils import convert_trio_resource_errors, silently_close_socket_in_destructor
from .socket import TrioStreamSocketAdapter


@final
class TrioListenerSocketAdapter(AsyncListener[TrioStreamSocketAdapter]):
    __slots__ = (
        "__backend",
        "__listener",
        "__trsock",
        "__serve_guard",
    )

    def __init__(self, backend: AsyncBackend, listener: trio.SocketListener) -> None:
        super().__init__()

        self.__backend: AsyncBackend = backend
        self.__listener: trio.SocketListener = listener
        self.__trsock: socket_tools.SocketProxy = socket_tools.SocketProxy(listener.socket)
        self.__serve_guard: _utils.ResourceGuard = _utils.ResourceGuard(f"{self.__class__.__name__}.serve() awaited twice.")

    def __del__(self, *, _warn: _utils.WarnCallback = warnings.warn) -> None:
        try:
            listener = self.__listener
        except AttributeError:
            listener = None
        if listener is not None and listener.socket.fileno() >= 0:
            _warn(f"unclosed listener {self!r}", ResourceWarning, source=self)
            silently_close_socket_in_destructor(listener.socket)

    async def aclose(self) -> None:
        return await self.__listener.aclose()

    def is_closing(self) -> bool:
        return self.__listener.socket.fileno() < 0

    async def serve(
        self,
        handler: Callable[[TrioStreamSocketAdapter], Coroutine[Any, Any, None]],
        task_group: TaskGroup | None = None,
    ) -> NoReturn:
        async with contextlib.AsyncExitStack() as stack:
            stack.enter_context(self.__serve_guard)
            if task_group is None:
                task_group = await stack.enter_async_context(self.__backend.create_task_group())
            stack.enter_context(convert_trio_resource_errors())

            while True:
                # Always drop socket reference on loop begin
                client_socket: trio.SocketStream | None = None

                client_socket = await self.__listener.accept()
                task_group.start_soon(handler, TrioStreamSocketAdapter(self.__backend, client_socket))

        raise AssertionError("Expected code to be unreachable.")

    def backend(self) -> AsyncBackend:
        return self.__backend

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return socket_tools._get_socket_extra(self.__trsock, wrap_in_proxy=False)
