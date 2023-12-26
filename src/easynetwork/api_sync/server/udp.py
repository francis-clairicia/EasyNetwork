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

import contextlib
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Generic

from ..._typevars import _T_Request, _T_Response
from ...api_async.server.udp import AsyncUDPNetworkServer
from ...lowlevel import _utils
from ...lowlevel.socket import SocketProxy
from . import _base

if TYPE_CHECKING:
    import logging

    from ...api_async.server.handler import AsyncDatagramRequestHandler
    from ...protocol import DatagramProtocol


class StandaloneUDPNetworkServer(_base.BaseStandaloneNetworkServerImpl, Generic[_T_Request, _T_Response]):
    """
    A network server for UDP communication.

    It embeds an :class:`.AsyncUDPNetworkServer` instance.
    """

    __slots__ = ()

    def __init__(
        self,
        host: str | None | Sequence[str],
        port: int,
        protocol: DatagramProtocol[_T_Response, _T_Request],
        request_handler: AsyncDatagramRequestHandler[_T_Request, _T_Response],
        backend: str = "asyncio",
        *,
        reuse_port: bool = False,
        logger: logging.Logger | None = None,
        **kwargs: Any,
    ) -> None:
        """
        For the arguments, see :class:`.AsyncUDPNetworkServer` documentation.

        Note:
            The backend interface must be explicitly given. It defaults to ``asyncio``.
        """
        super().__init__(
            backend,
            _utils.make_callback(
                AsyncUDPNetworkServer,  # type: ignore[arg-type]
                host=host,
                port=port,
                protocol=protocol,
                request_handler=request_handler,
                reuse_port=reuse_port,
                logger=logger,
                **kwargs,
            ),
        )

    def get_sockets(self) -> Sequence[SocketProxy]:
        """Gets the listeners sockets. Thread-safe.

        Returns:
            a read-only sequence of :class:`.SocketProxy` objects.

            If the server is not running, an empty sequence is returned.
        """
        if (portal := self._portal) is not None and (server := self._server) is not None:
            with contextlib.suppress(RuntimeError):
                sockets = portal.run_sync(server.get_sockets)
                return tuple(SocketProxy(sock, runner=portal.run_sync) for sock in sockets)
        return ()

    if TYPE_CHECKING:

        @property
        def _server(self) -> AsyncUDPNetworkServer[_T_Request, _T_Response] | None:
            ...
