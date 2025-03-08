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

__all__ = ["TrioListenerSocketAdapter"]

import contextlib
import errno as _errno
import logging
import os
import warnings
from collections.abc import Callable, Coroutine, Mapping
from types import MappingProxyType
from typing import Any, NoReturn, final

import trio

from ..... import _utils, constants, socket as socket_tools
from ....transports.abc import AsyncListener
from ...abc import AsyncBackend, TaskGroup
from .._trio_utils import convert_trio_resource_errors
from .socket import TrioStreamSocketAdapter


@final
class TrioListenerSocketAdapter(AsyncListener[TrioStreamSocketAdapter]):
    __slots__ = (
        "__backend",
        "__listener",
        "__serve_guard",
        "__extra_attributes",
    )

    def __init__(self, backend: AsyncBackend, listener: trio.SocketListener) -> None:
        super().__init__()

        self.__backend: AsyncBackend = backend
        self.__listener: trio.SocketListener = listener
        self.__serve_guard: _utils.ResourceGuard = _utils.ResourceGuard(f"{self.__class__.__name__}.serve() awaited twice.")
        self.__extra_attributes = MappingProxyType(socket_tools._get_socket_extra(listener.socket))

    def __del__(self, *, _warn: _utils.WarnCallback = warnings.warn) -> None:
        try:
            listener = self.__listener
        except AttributeError:  # pragma: no cover
            # Technically possible but not with the common usage because this constructor does not raise.
            listener = None
        if listener is not None and listener.socket.fileno() >= 0:
            _warn(f"unclosed listener {self!r}", ResourceWarning, source=self)
            listener.socket.close()

    async def aclose(self) -> None:
        return await self.__listener.aclose()

    def is_closing(self) -> bool:
        return self.__listener.socket.fileno() < 0

    async def serve(
        self,
        handler: Callable[[TrioStreamSocketAdapter], Coroutine[Any, Any, None]],
        task_group: TaskGroup | None = None,
    ) -> NoReturn:
        from errno import EBADF

        async with contextlib.AsyncExitStack() as stack:
            stack.enter_context(self.__serve_guard)
            if task_group is None:
                task_group = await stack.enter_async_context(self.__backend.create_task_group())
            stack.enter_context(convert_trio_resource_errors(broken_resource_errno=EBADF))

            while True:
                # Always drop socket reference on loop begin
                client_socket: trio.SocketStream | None = None

                try:
                    client_socket = await self.__listener.accept()
                except OSError as exc:
                    if exc.errno in constants.ACCEPT_CAPACITY_ERRNOS:
                        logger = logging.getLogger(__name__)
                        logger.error(
                            "accept returned %s (%s); retrying in %s seconds",
                            _errno.errorcode[exc.errno],
                            os.strerror(exc.errno),
                            constants.ACCEPT_CAPACITY_ERROR_SLEEP_TIME,
                            exc_info=exc,
                        )
                        await trio.sleep(constants.ACCEPT_CAPACITY_ERROR_SLEEP_TIME)
                    else:
                        raise
                else:
                    task_group.start_soon(handler, TrioStreamSocketAdapter(self.__backend, client_socket))

        raise AssertionError("Expected code to be unreachable.")

    def backend(self) -> AsyncBackend:
        return self.__backend

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__extra_attributes
