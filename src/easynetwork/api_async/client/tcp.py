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
"""Asynchronous network client module"""

from __future__ import annotations

__all__ = ["AsyncTCPNetworkClient"]

import contextlib
import dataclasses
import errno as _errno
import socket as _socket
from collections.abc import Awaitable, Callable, Iterator
from typing import TYPE_CHECKING, Any, final, overload

try:
    import ssl as _ssl
except ImportError:  # pragma: no cover
    _ssl_module = None
else:
    _ssl_module = _ssl
    del _ssl

from ..._typevars import _ReceivedPacketT, _SentPacketT
from ...exceptions import ClientClosedError
from ...lowlevel import _utils, constants
from ...lowlevel.api_async.backend.abc import CancelScope, ILock
from ...lowlevel.api_async.backend.factory import current_async_backend
from ...lowlevel.api_async.endpoints.stream import AsyncStreamEndpoint
from ...lowlevel.api_async.transports.abc import AsyncStreamTransport
from ...lowlevel.socket import (
    INETSocketAttribute,
    SocketAddress,
    SocketProxy,
    new_socket_address,
    set_tcp_keepalive,
    set_tcp_nodelay,
)
from ...protocol import StreamProtocol
from .abc import AbstractAsyncNetworkClient

if TYPE_CHECKING:
    import ssl as _typing_ssl


@dataclasses.dataclass(kw_only=True, slots=True)
class _SocketConnector:
    lock: ILock
    factory: Callable[[], Awaitable[tuple[AsyncStreamTransport, SocketProxy]]] | None
    scope: CancelScope
    _result: tuple[AsyncStreamTransport, SocketProxy] | None = dataclasses.field(init=False, default=None)

    async def get(self) -> tuple[AsyncStreamTransport, SocketProxy] | None:
        async with self.lock:
            factory, self.factory = self.factory, None
            if factory is not None:
                with self.scope:
                    self._result = await factory()
        return self._result


class AsyncTCPNetworkClient(AbstractAsyncNetworkClient[_SentPacketT, _ReceivedPacketT]):
    """
    An asynchronous network client interface for TCP connections.
    """

    __slots__ = (
        "__endpoint",
        "__protocol",
        "__socket_connector",
        "__socket_proxy",
        "__receive_lock",
        "__send_lock",
        "__expected_recv_size",
    )

    @overload
    def __init__(
        self,
        address: tuple[str, int],
        /,
        protocol: StreamProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        local_address: tuple[str, int] | None = ...,
        happy_eyeballs_delay: float | None = ...,
        ssl: _typing_ssl.SSLContext | bool | None = ...,
        server_hostname: str | None = ...,
        ssl_handshake_timeout: float | None = ...,
        ssl_shutdown_timeout: float | None = ...,
        ssl_shared_lock: bool | None = ...,
        max_recv_size: int | None = ...,
    ) -> None:
        ...

    @overload
    def __init__(
        self,
        socket: _socket.socket,
        /,
        protocol: StreamProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        ssl: _typing_ssl.SSLContext | bool | None = ...,
        server_hostname: str | None = ...,
        ssl_handshake_timeout: float | None = ...,
        ssl_shutdown_timeout: float | None = ...,
        ssl_shared_lock: bool | None = ...,
        max_recv_size: int | None = ...,
    ) -> None:
        ...

    def __init__(
        self,
        __arg: tuple[str, int] | _socket.socket,
        /,
        protocol: StreamProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        ssl: _typing_ssl.SSLContext | bool | None = None,
        server_hostname: str | None = None,
        ssl_handshake_timeout: float | None = None,
        ssl_shutdown_timeout: float | None = None,
        ssl_shared_lock: bool | None = None,
        max_recv_size: int | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Common Parameters:
            protocol: The :term:`protocol object` to use.

        Connection Parameters:
            address: A pair of ``(host, port)`` for connection.
            happy_eyeballs_delay: the "Connection Attempt Delay" as defined in :rfc:`8305`.
                                  A sensible default value recommended by the RFC is 0.25 (250 milliseconds).
            local_address: If given, is a ``(local_host, local_port)`` tuple used to bind the socket locally.

        Socket Parameters:
            socket: An already connected TCP :class:`socket.socket`. If `socket` is given,
                    none of `happy_eyeballs_delay` and `local_address` should be specified.

        Keyword Arguments:
            ssl: If given and not false, a SSL/TLS transport is created (by default a plain TCP transport is created).
                 If ssl is a :class:`ssl.SSLContext` object, this context is used to create the transport;
                 if ssl is :data:`True`, a default context returned from :func:`ssl.create_default_context` is used.
            server_hostname: sets or overrides the hostname that the target server's certificate will be matched against.
                             Should only be passed if `ssl` is not :data:`None`. By default the value of the host in `address`
                             argument is used. If `socket` is provided instead, there is no default and you must pass a value
                             for `server_hostname`. If `server_hostname` is an empty string, hostname matching is disabled
                             (which is a serious security risk, allowing for potential man-in-the-middle attacks).
            ssl_handshake_timeout: (for a TLS connection) the time in seconds to wait for the TLS handshake to complete
                                   before aborting the connection. ``60.0`` seconds if :data:`None` (default).
            ssl_shutdown_timeout: the time in seconds to wait for the SSL shutdown to complete before aborting the connection.
                                  ``30.0`` seconds if :data:`None` (default).
            ssl_shared_lock: If :data:`True` (the default), :meth:`send_packet` and :meth:`recv_packet` uses
                             the same lock instance.
            max_recv_size: Read buffer size. If not given, a default reasonable value is used.

        See Also:
            :ref:`SSL/TLS security considerations <ssl-security>`
        """
        super().__init__()

        if not isinstance(protocol, StreamProtocol):
            raise TypeError(f"Expected a StreamProtocol object, got {protocol!r}")

        backend = current_async_backend()
        if max_recv_size is None:
            max_recv_size = constants.DEFAULT_STREAM_BUFSIZE
        if not isinstance(max_recv_size, int) or max_recv_size <= 0:
            raise ValueError("'max_recv_size' must be a strictly positive integer")

        self.__endpoint: AsyncStreamEndpoint[_SentPacketT, _ReceivedPacketT] | None = None
        self.__socket_proxy: SocketProxy | None = None
        self.__protocol: StreamProtocol[_SentPacketT, _ReceivedPacketT] = protocol

        if ssl:
            if _ssl_module is None:
                raise RuntimeError("stdlib ssl module not available")
            if isinstance(ssl, bool):
                ssl = _ssl_module.create_default_context()
                assert isinstance(ssl, _ssl_module.SSLContext)  # nosec assert_used
                if server_hostname is not None and not server_hostname:
                    ssl.check_hostname = False
        else:
            if server_hostname is not None:
                raise ValueError("server_hostname is only meaningful with ssl")

            if ssl_handshake_timeout is not None:
                raise ValueError("ssl_handshake_timeout is only meaningful with ssl")

            if ssl_shutdown_timeout is not None:
                raise ValueError("ssl_shutdown_timeout is only meaningful with ssl")

            if ssl_shared_lock is not None:
                raise ValueError("ssl_shared_lock is only meaningful with ssl")

        if ssl_shared_lock is None:
            ssl_shared_lock = True

        def _value_or_default(value: float | None, default: float) -> float:
            return value if value is not None else default

        socket_factory: Callable[[], Awaitable[AsyncStreamTransport]]
        match __arg:
            case _socket.socket() as socket:
                _utils.check_socket_no_ssl(socket)
                _utils.check_socket_family(socket.family)
                _utils.check_socket_is_connected(socket)
                if ssl:
                    if server_hostname is None:
                        raise ValueError("You must set server_hostname when using ssl without a host")
                    socket_factory = _utils.make_callback(
                        backend.wrap_ssl_over_stream_socket_client_side,
                        socket,
                        ssl_context=ssl,
                        server_hostname=server_hostname,
                        ssl_handshake_timeout=_value_or_default(ssl_handshake_timeout, constants.SSL_HANDSHAKE_TIMEOUT),
                        ssl_shutdown_timeout=_value_or_default(ssl_shutdown_timeout, constants.SSL_SHUTDOWN_TIMEOUT),
                        **kwargs,
                    )
                else:
                    socket_factory = _utils.make_callback(backend.wrap_stream_socket, socket, **kwargs)
            case (str(host), int(port)):
                if ssl:
                    socket_factory = _utils.make_callback(
                        backend.create_ssl_over_tcp_connection,
                        host,
                        port,
                        ssl_context=ssl,
                        server_hostname=server_hostname,
                        ssl_handshake_timeout=_value_or_default(ssl_handshake_timeout, constants.SSL_HANDSHAKE_TIMEOUT),
                        ssl_shutdown_timeout=_value_or_default(ssl_shutdown_timeout, constants.SSL_SHUTDOWN_TIMEOUT),
                        **kwargs,
                    )
                else:
                    socket_factory = _utils.make_callback(backend.create_tcp_connection, host, port, **kwargs)
            case _:  # pragma: no cover
                raise TypeError("Invalid arguments")

        self.__socket_connector: _SocketConnector | None = _SocketConnector(
            lock=backend.create_lock(),
            factory=_utils.make_callback(self.__create_socket, socket_factory),
            scope=backend.open_cancel_scope(),
        )

        assert ssl_shared_lock is not None  # nosec assert_used

        self.__receive_lock: ILock
        self.__send_lock: ILock
        if ssl and ssl_shared_lock:
            self.__send_lock = self.__receive_lock = backend.create_lock()
        else:
            self.__receive_lock = backend.create_lock()
            self.__send_lock = backend.create_lock()
        self.__expected_recv_size: int = max_recv_size

    def __repr__(self) -> str:
        try:
            endpoint = self.__endpoint
            if endpoint is None:
                raise AttributeError
        except AttributeError:
            return f"<{type(self).__name__} (partially initialized)>"
        return f"<{type(self).__name__} endpoint={endpoint!r}>"

    def is_connected(self) -> bool:
        """
        Checks if the client initialization is finished.

        See Also:
            :meth:`wait_connected` method.

        Returns:
            the client connection state.
        """
        return self.__endpoint is not None

    async def wait_connected(self) -> None:
        """
        Finishes initializing the client, doing the asynchronous operations that could not be done in the constructor.
        Does not require task synchronization.

        It is not needed to call it directly if the client is used as an :term:`asynchronous context manager`::

            async with client:  # wait_connected() has been called.
                ...

        Can be safely called multiple times.

        Warning:
            Due to limitations of the underlying operating system APIs,
            it is not always possible to properly cancel a connection attempt once it has begun.

            If :meth:`wait_connected` is cancelled, and is unable to abort the connection attempt, then it will forcibly
            close the socket to prevent accidental re-use.

        Raises:
            ClientClosedError: the client object is closed.
            ConnectionError: could not connect to remote.
            OSError: unrelated OS error occurred. You should check :attr:`OSError.errno`.
        """
        await self.__ensure_connected()

    @staticmethod
    async def __create_socket(
        socket_factory: Callable[[], Awaitable[AsyncStreamTransport]],
    ) -> tuple[AsyncStreamTransport, SocketProxy]:
        transport = await socket_factory()

        socket_proxy = SocketProxy(transport.extra(INETSocketAttribute.socket))

        _utils.check_socket_family(socket_proxy.family)

        with contextlib.suppress(OSError):
            set_tcp_nodelay(socket_proxy, True)
        with contextlib.suppress(OSError):
            set_tcp_keepalive(socket_proxy, True)
        return transport, socket_proxy

    def is_closing(self) -> bool:
        """
        Checks if the client is closed or in the process of being closed.

        If :data:`True`, all future operations on the client object will raise a :exc:`.ClientClosedError`.

        See Also:
            :meth:`aclose` method.

        Returns:
            the client state.
        """
        if self.__socket_connector is not None:
            return False
        endpoint = self.__endpoint
        return endpoint is None or endpoint.is_closing()

    async def aclose(self) -> None:
        """
        Close the client. Does not require task synchronization.

        Once that happens, all future operations on the client object will raise a :exc:`.ClientClosedError`.
        The remote end will receive no more data (after queued data is flushed).

        Warning:
            :meth:`aclose` performs a graceful close, waiting for the connection to close.

            If :meth:`aclose` is cancelled, the client is closed abruptly.

        Can be safely called multiple times.
        """
        if self.__socket_connector is not None:
            self.__socket_connector.scope.cancel()
            self.__socket_connector = None
        async with self.__send_lock:
            if self.__endpoint is None:
                return
            await self.__endpoint.aclose()

    async def send_packet(self, packet: _SentPacketT) -> None:
        """
        Sends `packet` to the remote endpoint. Does not require task synchronization.

        Warning:
            In the case of a cancellation, it is impossible to know if all the packet data has been sent.
            This would leave the connection in an inconsistent state.

        Parameters:
            packet: the Python object to send.

        Raises:
            ClientClosedError: the client object is closed.
            ConnectionError: connection unexpectedly closed during operation.
                             You should not attempt any further operation and close the client object.
            OSError: unrelated OS error occurred. You should check :attr:`OSError.errno`.
            RuntimeError: :meth:`send_eof` has been called earlier.
        """
        async with self.__send_lock:
            endpoint = await self.__ensure_connected()
            with self.__convert_socket_error():
                await endpoint.send_packet(packet)
                _utils.check_real_socket_state(endpoint.extra(INETSocketAttribute.socket))

    async def send_eof(self) -> None:
        """
        Close the write end of the stream after the buffered write data is flushed. Does not require task synchronization.

        Can be safely called multiple times.

        Raises:
            OSError: unrelated OS error occurred. You should check :attr:`OSError.errno`.
        """
        async with self.__send_lock:
            try:
                endpoint = await self.__ensure_connected()
            except ClientClosedError:
                return
            await endpoint.send_eof()

    async def recv_packet(self) -> _ReceivedPacketT:
        """
        Waits for a new packet to arrive from the remote endpoint. Does not require task synchronization.

        Raises:
            ClientClosedError: the client object is closed.
            ConnectionError: connection unexpectedly closed during operation.
                             You should not attempt any further operation and close the client object.
            OSError: unrelated OS error occurred. You should check :attr:`OSError.errno`.
            StreamProtocolParseError: invalid data received.

        Returns:
            the received packet.
        """
        async with self.__receive_lock:
            endpoint = await self.__ensure_connected()
            try:
                with self.__convert_socket_error():
                    return await endpoint.recv_packet()
            except EOFError:
                raise self.__abort() from None

    def get_local_address(self) -> SocketAddress:
        """
        Returns the local socket IP address.

        If :meth:`wait_connected` was not called, an :exc:`OSError` may occurr.

        Raises:
            ClientClosedError: the client object is closed.
            OSError: unrelated OS error occurred. You should check :attr:`OSError.errno`.

        Returns:
            the client's local address.
        """
        endpoint = self.__get_endpoint_sync()
        local_address = endpoint.extra(INETSocketAttribute.sockname)
        address_family = endpoint.extra(INETSocketAttribute.family)
        return new_socket_address(local_address, address_family)

    def get_remote_address(self) -> SocketAddress:
        """
        Returns the remote socket IP address.

        If :meth:`wait_connected` was not called, an :exc:`OSError` may occurr.

        Raises:
            ClientClosedError: the client object is closed.
            OSError: unrelated OS error occurred. You should check :attr:`OSError.errno`.

        Returns:
            the client's remote address.
        """
        endpoint = self.__get_endpoint_sync()
        remote_address = endpoint.extra(INETSocketAttribute.peername)
        address_family = endpoint.extra(INETSocketAttribute.family)
        return new_socket_address(remote_address, address_family)

    async def __ensure_connected(self) -> AsyncStreamEndpoint[_SentPacketT, _ReceivedPacketT]:
        if self.__endpoint is None:
            endpoint_and_proxy = None
            if (socket_connector := self.__socket_connector) is not None:
                endpoint_and_proxy = await socket_connector.get()
            self.__socket_connector = None
            if endpoint_and_proxy is None:
                raise self.__closed()
            if self.__endpoint is None:
                transport, self.__socket_proxy = endpoint_and_proxy
                self.__endpoint = AsyncStreamEndpoint(transport, self.__protocol, max_recv_size=self.__expected_recv_size)

        if self.__endpoint.is_closing():
            raise self.__closed()
        return self.__endpoint

    def __get_endpoint_sync(self) -> AsyncStreamEndpoint[_SentPacketT, _ReceivedPacketT]:
        if self.__endpoint is None:
            if self.__socket_connector is not None:
                raise _utils.error_from_errno(_errno.ENOTSOCK)
            else:
                raise self.__closed()
        if self.__endpoint.is_closing():
            raise self.__closed()
        return self.__endpoint

    @contextlib.contextmanager
    def __convert_socket_error(self) -> Iterator[None]:
        try:
            yield
        except ConnectionError as exc:
            raise self.__abort() from exc
        except OSError as exc:
            if exc.errno in constants.CLOSED_SOCKET_ERRNOS:
                raise self.__closed()
            raise

    @staticmethod
    def __abort() -> OSError:
        return _utils.error_from_errno(_errno.ECONNABORTED)

    @staticmethod
    def __closed() -> ClientClosedError:
        return ClientClosedError("Client is closing, or is already closed")

    @property
    @final
    def socket(self) -> SocketProxy:
        """A view to the underlying socket instance. Read-only attribute.

        May raise :exc:`AttributeError` if :meth:`wait_connected` was not called.
        """
        if self.__socket_proxy is None:
            raise AttributeError("Socket not connected")
        return self.__socket_proxy

    @property
    @final
    def max_recv_size(self) -> int:
        """Read buffer size. Read-only attribute."""
        endpoint = self.__endpoint
        if endpoint is None:
            return self.__expected_recv_size
        return endpoint.max_recv_size
