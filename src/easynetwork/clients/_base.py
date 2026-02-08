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
"""Internal helper for client implementations."""

from __future__ import annotations

__all__ = [
    "DeferredAsyncEndpointInit",
]

import contextlib
import dataclasses
import errno as _errno
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Generic, TypeVar

try:
    import ssl
except ImportError:  # pragma: no cover
    _ssl_module = None
else:
    _ssl_module = ssl
    del ssl


from ..exceptions import ClientClosedError
from ..lowlevel import _utils, constants
from ..lowlevel.api_async.backend.abc import AsyncBackend, CancelScope, ILock
from ..lowlevel.api_async.transports.abc import AsyncBaseTransport
from ..lowlevel.api_async.transports.utils import aclose_forcefully

if TYPE_CHECKING:
    from ssl import SSLContext

_T_Endpoint = TypeVar("_T_Endpoint", bound=AsyncBaseTransport)


@dataclasses.dataclass(kw_only=True, slots=True)
class _AsyncTransportConnector(Generic[_T_Endpoint]):
    endpoint_factory: Callable[[], Awaitable[_T_Endpoint]]
    scope: CancelScope

    async def get(self) -> _T_Endpoint | None:
        endpoint: _T_Endpoint | None = None
        with self.scope:
            endpoint = await self.endpoint_factory()
        if endpoint is not None and self.scope.cancel_called():
            await aclose_forcefully(endpoint)
            endpoint = None
        return endpoint


class DeferredAsyncEndpointInit(Generic[_T_Endpoint]):
    __slots__ = (
        "__backend",
        "__endpoint",
        "__transport_connector",
        "__transport_connector_lock",
    )

    def __init__(
        self,
        *,
        backend: AsyncBackend,
        endpoint_factory: Callable[[], Awaitable[_T_Endpoint]],
    ) -> None:
        self.__backend: AsyncBackend = backend
        self.__endpoint: _T_Endpoint | None = None
        self.__transport_connector: _AsyncTransportConnector[_T_Endpoint] | None = _AsyncTransportConnector(
            endpoint_factory=endpoint_factory,
            scope=backend.open_cancel_scope(),
        )
        self.__transport_connector_lock: ILock = backend.create_lock()

    def get_endpoint_unchecked(self) -> _T_Endpoint | None:
        return self.__endpoint

    def is_closing(self) -> bool:
        if self.__transport_connector is not None:
            return False
        return (endpoint := self.__endpoint) is None or endpoint.is_closing()

    def is_connected(self) -> bool:
        return self.__endpoint is not None

    async def aclose(self) -> None:
        if self.__transport_connector is not None:
            self.__transport_connector.scope.cancel()
            self.__transport_connector = None
        if self.__endpoint is None:
            return
        await self.__endpoint.aclose()

    async def connect(self) -> _T_Endpoint:
        async with self.__transport_connector_lock:
            if self.__endpoint is None:
                endpoint = None
                if (transport_connector := self.__transport_connector) is not None:
                    endpoint = await transport_connector.get()
                self.__transport_connector = None
                if endpoint is None:
                    raise self.__closed()
                self.__endpoint = endpoint

            # If you want coverage.py to work properly, keep this "pass" :)
            pass

        if self.__endpoint.is_closing():
            raise self.__closed()
        return self.__endpoint

    def get_sync(self) -> _T_Endpoint:
        if self.__endpoint is None:
            if self.__transport_connector is not None:
                raise _utils.error_from_errno(_errno.ENOTCONN)
            else:
                raise self.__closed()
        if self.__endpoint.is_closing():
            raise self.__closed()
        return self.__endpoint

    def backend(self) -> AsyncBackend:
        # Adding this method enables the use of aclose_forcefully()
        return self.__backend

    @staticmethod
    def __closed() -> ClientClosedError:
        return ClientClosedError("Client is closing, or is already closed")


def validate_max_recv_size(max_recv_size: int | None) -> int:
    if max_recv_size is None:
        max_recv_size = constants.DEFAULT_STREAM_BUFSIZE
    if not isinstance(max_recv_size, int) or max_recv_size <= 0:
        raise ValueError("'max_recv_size' must be a strictly positive integer")
    return max_recv_size


def validate_ssl_arguments(
    *,
    ssl: SSLContext | bool | None,
    server_hostname: str | None,
    ssl_handshake_timeout: float | None,
    ssl_shutdown_timeout: float | None,
    ssl_standard_compatible: bool | None,
) -> None:
    if server_hostname is not None and not ssl:
        raise ValueError("server_hostname is only meaningful with ssl")

    if ssl_handshake_timeout is not None and not ssl:
        raise ValueError("ssl_handshake_timeout is only meaningful with ssl")

    if ssl_shutdown_timeout is not None and not ssl:
        raise ValueError("ssl_shutdown_timeout is only meaningful with ssl")

    if ssl_standard_compatible is not None and not ssl:
        raise ValueError("ssl_standard_compatible is only meaningful with ssl")


def resolve_ssl_context(ssl: SSLContext | bool | None, server_hostname: str | None) -> SSLContext | None:
    if not ssl:
        return None

    if _ssl_module is None:
        raise RuntimeError("stdlib ssl module not available")
    if isinstance(ssl, bool):
        ssl = _ssl_module.create_default_context()
        assert isinstance(ssl, _ssl_module.SSLContext)  # nosec assert_used
        if server_hostname is not None and not server_hostname:
            ssl.check_hostname = False
        with contextlib.suppress(AttributeError):
            ssl.options &= ~_ssl_module.OP_IGNORE_UNEXPECTED_EOF
    return ssl


def resolve_server_hostname_for_ssl(server_hostname: str | None, host_address: str) -> str | None:
    if server_hostname is None:
        # Use host as default for server_hostname.  It is an error
        # if host is empty or not set, e.g. when an
        # already-connected socket was passed or when only a port
        # is given.  To avoid this error, you can pass
        # server_hostname='' -- this will bypass the hostname
        # check.  (This also means that if host is a numeric
        # IP/IPv6 address, we will attempt to verify that exact
        # address; this will probably fail, but it is possible to
        # create a certificate for a specific IP address, so we
        # don't judge it here.)
        if not host_address:
            raise ValueError("You must set server_hostname when using ssl without a host")
        server_hostname = host_address
    return server_hostname
