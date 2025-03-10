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
"""Unix datagram server implementation module.

.. versionadded:: 1.1
"""

from __future__ import annotations

__all__ = [
    "StandaloneUnixDatagramServer",
]

import logging
import os
from collections.abc import Mapping, Sequence
from typing import Any, Generic

from .._typevars import _T_Request, _T_Response
from ..lowlevel.api_async.backend.abc import AsyncBackend
from ..lowlevel.api_async.backend.utils import BuiltinAsyncBackendLiteral
from ..lowlevel.socket import SocketProxy, UnixSocketAddress
from ..protocol import DatagramProtocol
from . import _base
from .async_unix_datagram import AsyncUnixDatagramServer, _UnnamedAddressesBehavior
from .handlers import AsyncDatagramRequestHandler


class StandaloneUnixDatagramServer(
    _base.BaseStandaloneNetworkServerImpl[AsyncUnixDatagramServer[_T_Request, _T_Response]],
    Generic[_T_Request, _T_Response],
):
    """
    A Unix datagram server.

    It embeds an :class:`.AsyncUnixDatagramServer` instance.

    .. versionadded:: 1.1
    """

    __slots__ = ()

    def __init__(
        self,
        path: str | os.PathLike[str] | bytes | UnixSocketAddress,
        protocol: DatagramProtocol[_T_Response, _T_Request],
        request_handler: AsyncDatagramRequestHandler[_T_Request, _T_Response],
        backend: AsyncBackend | BuiltinAsyncBackendLiteral | None = None,
        *,
        runner_options: Mapping[str, Any] | None = None,
        mode: int | None = None,
        unnamed_addresses_behavior: _UnnamedAddressesBehavior | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        """
        For the other arguments, see :class:`.AsyncUnixDatagramServer` documentation.

        Parameters:
            backend: The :term:`asynchronous backend interface` to use. It defaults to :mod:`asyncio` implementation.
            runner_options: Options to pass to the :meth:`.AsyncBackend.bootstrap` method.
        """
        super().__init__(
            backend,
            lambda backend: AsyncUnixDatagramServer(
                path=path,
                protocol=protocol,
                backend=backend,
                request_handler=request_handler,
                mode=mode,
                unnamed_addresses_behavior=unnamed_addresses_behavior,
                logger=logger,
            ),
            runner_options=runner_options,
        )

    def get_addresses(self) -> Sequence[UnixSocketAddress]:
        """
        Returns all interfaces to which the server is bound. Thread-safe.

        Returns:
            A sequence of socket address.
            If the server is not serving (:meth:`is_serving` returns :data:`False`), an empty sequence is returned.
        """
        return self._run_sync_or(lambda portal, server: portal.run_sync(server.get_addresses), ())

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
