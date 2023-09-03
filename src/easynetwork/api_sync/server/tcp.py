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
"""Asynchronous network server module"""

from __future__ import annotations

__all__ = [
    "StandaloneTCPNetworkServer",
]

import contextlib as _contextlib
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Generic

from ..._typevars import _RequestT, _ResponseT
from ...api_async.server.tcp import AsyncTCPNetworkServer
from ...tools.socket import SocketAddress, SocketProxy
from . import _base

if TYPE_CHECKING:
    import logging as _logging
    from ssl import SSLContext as _SSLContext

    from ...api_async.backend.abc import AsyncBackend
    from ...api_async.server.handler import AsyncStreamRequestHandler
    from ...protocol import StreamProtocol


class StandaloneTCPNetworkServer(_base.BaseStandaloneNetworkServerImpl, Generic[_RequestT, _ResponseT]):
    __slots__ = ()

    def __init__(
        self,
        host: str | None | Sequence[str],
        port: int,
        protocol: StreamProtocol[_ResponseT, _RequestT],
        request_handler: AsyncStreamRequestHandler[_RequestT, _ResponseT],
        backend: str | AsyncBackend = "asyncio",
        *,
        ssl: _SSLContext | None = None,
        ssl_handshake_timeout: float | None = None,
        ssl_shutdown_timeout: float | None = None,
        backlog: int | None = None,
        reuse_port: bool = False,
        max_recv_size: int | None = None,
        backend_kwargs: Mapping[str, Any] | None = None,
        log_client_connection: bool | None = None,
        logger: _logging.Logger | None = None,
        **kwargs: Any,
    ) -> None:
        if backend is None:
            raise ValueError("You must explicitly give a backend name or instance")
        super().__init__(
            AsyncTCPNetworkServer(
                host=host,
                port=port,
                protocol=protocol,
                request_handler=request_handler,
                ssl=ssl,
                ssl_handshake_timeout=ssl_handshake_timeout,
                ssl_shutdown_timeout=ssl_shutdown_timeout,
                backlog=backlog,
                reuse_port=reuse_port,
                max_recv_size=max_recv_size,
                backend=backend,
                backend_kwargs=backend_kwargs,
                log_client_connection=log_client_connection,
                logger=logger,
                **kwargs,
            )
        )

    def stop_listening(self) -> None:
        if (portal := self._portal) is not None:
            with _contextlib.suppress(RuntimeError):
                portal.run_sync(self._server.stop_listening)

    def get_addresses(self) -> Sequence[SocketAddress]:
        if (portal := self._portal) is not None:
            with _contextlib.suppress(RuntimeError):
                return portal.run_sync(self._server.get_addresses)
        return ()

    @property
    def sockets(self) -> Sequence[SocketProxy]:
        if (portal := self._portal) is not None:
            with _contextlib.suppress(RuntimeError):
                sockets = portal.run_sync(lambda: self._server.sockets)
                return tuple(SocketProxy(sock, runner=portal.run_sync) for sock in sockets)
        return ()

    @property
    def logger(self) -> _logging.Logger:
        return self._server.logger

    if TYPE_CHECKING:

        @property
        def _server(self) -> AsyncTCPNetworkServer[_RequestT, _ResponseT]:
            ...
