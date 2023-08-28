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
    "StandaloneUDPNetworkServer",
]

import contextlib as _contextlib
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Generic

from ..._typevars import _RequestT, _ResponseT
from ...api_async.server.udp import AsyncUDPNetworkServer
from ...tools.socket import SocketAddress, SocketProxy
from . import _base

if TYPE_CHECKING:
    import logging as _logging

    from ...api_async.backend.abc import AsyncBackend
    from ...api_async.server.handler import AsyncDatagramRequestHandler
    from ...protocol import DatagramProtocol


class StandaloneUDPNetworkServer(_base.BaseStandaloneNetworkServerImpl, Generic[_RequestT, _ResponseT]):
    __slots__ = ()

    def __init__(
        self,
        host: str,
        port: int,
        protocol: DatagramProtocol[_ResponseT, _RequestT],
        request_handler: AsyncDatagramRequestHandler[_RequestT, _ResponseT],
        backend: str | AsyncBackend = "asyncio",
        *,
        reuse_port: bool = False,
        backend_kwargs: Mapping[str, Any] | None = None,
        service_actions_interval: float | None = None,
        logger: _logging.Logger | None = None,
        **kwargs: Any,
    ) -> None:
        if backend is None:
            raise ValueError("You must explicitly give a backend name or instance")
        super().__init__(
            AsyncUDPNetworkServer(
                host=host,
                port=port,
                protocol=protocol,
                request_handler=request_handler,
                reuse_port=reuse_port,
                backend=backend,
                backend_kwargs=backend_kwargs,
                service_actions_interval=service_actions_interval,
                logger=logger,
                **kwargs,
            )
        )

    def get_address(self) -> SocketAddress | None:
        if (portal := self._portal) is not None:
            with _contextlib.suppress(RuntimeError):
                return portal.run_sync(self._server.get_address)
        return None

    @property
    def socket(self) -> SocketProxy | None:
        if (portal := self._portal) is not None:
            with _contextlib.suppress(RuntimeError):
                socket = portal.run_sync(lambda: self._server.socket)
                return SocketProxy(socket, runner=portal.run_sync) if socket is not None else None
        return None

    @property
    def logger(self) -> _logging.Logger:
        return self._server.logger

    if TYPE_CHECKING:

        @property
        def _server(self) -> AsyncUDPNetworkServer[_RequestT, _ResponseT]:
            ...
