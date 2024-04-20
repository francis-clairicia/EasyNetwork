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
"""Asynchronous network server module"""

from __future__ import annotations

__all__ = [
    "StandaloneUDPNetworkServer",
]

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Generic

from .._typevars import _T_Request, _T_Response
from ..lowlevel.api_async.backend.abc import AsyncBackend
from ..lowlevel.socket import SocketProxy
from . import _base
from .async_udp import AsyncUDPNetworkServer

if TYPE_CHECKING:
    import logging

    from ..protocol import DatagramProtocol
    from .handlers import AsyncDatagramRequestHandler


class StandaloneUDPNetworkServer(
    _base.BaseStandaloneNetworkServerImpl[AsyncUDPNetworkServer[_T_Request, _T_Response]],
    Generic[_T_Request, _T_Response],
):
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
        backend: AsyncBackend | None = None,
        *,
        runner_options: Mapping[str, Any] | None = None,
        reuse_port: bool = False,
        logger: logging.Logger | None = None,
        **kwargs: Any,
    ) -> None:
        """
        For the other arguments, see :class:`.AsyncUDPNetworkServer` documentation.

        Parameters:
            backend: The :term:`asynchronous backend interface` to use. It defaults to :mod:`asyncio` implementation.
            runner_options: Options to pass to the :meth:`.AsyncBackend.bootstrap` method.
        """
        super().__init__(
            backend,
            lambda backend: AsyncUDPNetworkServer(
                host=host,
                port=port,
                protocol=protocol,
                backend=backend,
                request_handler=request_handler,
                reuse_port=reuse_port,
                logger=logger,
                **kwargs,
            ),
            runner_options=runner_options,
        )

    def get_sockets(self) -> Sequence[SocketProxy]:
        """Gets the listeners sockets. Thread-safe.

        Returns:
            a read-only sequence of :class:`.SocketProxy` objects.

            If the server is not running, an empty sequence is returned.
        """
        return self._run_sync_or(
            lambda portal, server: tuple(
                SocketProxy(sock, runner=portal.run_sync) for sock in portal.run_sync(server.get_sockets)
            ),
            (),
        )
