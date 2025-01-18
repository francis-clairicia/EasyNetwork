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
"""Asynchronous TCP Network client implementation module."""

from __future__ import annotations

__all__ = ["AsyncTCPNetworkClient"]

import contextlib
import errno as _errno
import socket as _socket
import warnings
from collections.abc import Awaitable, Callable, Iterator
from typing import TYPE_CHECKING, Any, final, overload

try:
    import ssl as _ssl
except ImportError:  # pragma: no cover
    _ssl_module = None
else:
    _ssl_module = _ssl
    del _ssl

from .._typevars import _T_ReceivedPacket, _T_SentPacket
from ..exceptions import ClientClosedError
from ..lowlevel import _utils, constants
from ..lowlevel.api_async.backend.abc import AsyncBackend, ILock
from ..lowlevel.api_async.backend.utils import BuiltinAsyncBackendLiteral, ensure_backend
from ..lowlevel.api_async.endpoints.stream import AsyncStreamEndpoint
from ..lowlevel.api_async.transports.abc import AsyncStreamTransport
from ..lowlevel.api_async.transports.utils import aclose_forcefully
from ..lowlevel.socket import (
    INETSocketAttribute,
    SocketAddress,
    SocketProxy,
    new_socket_address,
    set_tcp_keepalive,
    set_tcp_nodelay,
)
from ..protocol import AnyStreamProtocolType
from . import _base
from .abc import AbstractAsyncNetworkClient

if TYPE_CHECKING:
    from ssl import SSLContext


class AsyncTCPNetworkClient(AbstractAsyncNetworkClient[_T_SentPacket, _T_ReceivedPacket]):
    """
    An asynchronous network client interface for TCP connections.
    """

    __slots__ = (
        "__backend",
        "__endpoint",
        "__socket_proxy",
        "__receive_lock",
        "__send_lock",
    )

    @overload
    def __init__(
        self,
        address: tuple[str, int],
        /,
        protocol: AnyStreamProtocolType[_T_SentPacket, _T_ReceivedPacket],
        backend: AsyncBackend | BuiltinAsyncBackendLiteral | None = ...,
        *,
        local_address: tuple[str, int] | None = ...,
        happy_eyeballs_delay: float | None = ...,
        ssl: SSLContext | bool | None = ...,
        server_hostname: str | None = ...,
        ssl_handshake_timeout: float | None = ...,
        ssl_shutdown_timeout: float | None = ...,
        ssl_standard_compatible: bool | None = ...,
        max_recv_size: int | None = ...,
    ) -> None: ...

    @overload
    def __init__(
        self,
        socket: _socket.socket,
        /,
        protocol: AnyStreamProtocolType[_T_SentPacket, _T_ReceivedPacket],
        backend: AsyncBackend | BuiltinAsyncBackendLiteral | None = ...,
        *,
        ssl: SSLContext | bool | None = ...,
        server_hostname: str | None = ...,
        ssl_handshake_timeout: float | None = ...,
        ssl_shutdown_timeout: float | None = ...,
        ssl_standard_compatible: bool | None = ...,
        max_recv_size: int | None = ...,
    ) -> None: ...

    def __init__(
        self,
        __arg: tuple[str, int] | _socket.socket,
        /,
        protocol: AnyStreamProtocolType[_T_SentPacket, _T_ReceivedPacket],
        backend: AsyncBackend | BuiltinAsyncBackendLiteral | None = None,
        *,
        ssl: SSLContext | bool | None = None,
        server_hostname: str | None = None,
        ssl_handshake_timeout: float | None = None,
        ssl_shutdown_timeout: float | None = None,
        ssl_standard_compatible: bool | None = None,
        max_recv_size: int | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Common Parameters:
            protocol: The :term:`protocol object` to use.
            backend: The :term:`asynchronous backend interface` to use.

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
            ssl_standard_compatible: if :data:`False`, skip the closing handshake when closing the connection,
                                     and don't raise an exception if the peer does the same.
            max_recv_size: Read buffer size. If not given, a default reasonable value is used.

        See Also:
            :ref:`SSL/TLS security considerations <ssl-security>`
        """
        super().__init__()

        from ..lowlevel._stream import _check_any_protocol

        _check_any_protocol(protocol)

        backend = ensure_backend(backend)

        if max_recv_size is None:
            max_recv_size = constants.DEFAULT_STREAM_BUFSIZE
        if not isinstance(max_recv_size, int) or max_recv_size <= 0:
            raise ValueError("'max_recv_size' must be a strictly positive integer")

        self.__backend: AsyncBackend = backend
        self.__socket_proxy: SocketProxy | None = None

        if ssl:
            if _ssl_module is None:
                raise RuntimeError("stdlib ssl module not available")
            if isinstance(ssl, bool):
                ssl = _ssl_module.create_default_context()
                assert isinstance(ssl, _ssl_module.SSLContext)  # nosec assert_used
                if server_hostname is not None and not server_hostname:
                    ssl.check_hostname = False
                with contextlib.suppress(AttributeError):
                    ssl.options &= ~_ssl_module.OP_IGNORE_UNEXPECTED_EOF
        else:
            if server_hostname is not None:
                raise ValueError("server_hostname is only meaningful with ssl")

            if ssl_handshake_timeout is not None:
                raise ValueError("ssl_handshake_timeout is only meaningful with ssl")

            if ssl_shutdown_timeout is not None:
                raise ValueError("ssl_shutdown_timeout is only meaningful with ssl")

            if ssl_standard_compatible is not None:
                raise ValueError("ssl_standard_compatible is only meaningful with ssl")

        if ssl_standard_compatible is None:
            ssl_standard_compatible = True

        socket_factory: Callable[[], Awaitable[AsyncStreamTransport]]
        match __arg:
            case _socket.socket() as socket:
                try:
                    _utils.check_socket_no_ssl(socket)
                    _utils.check_inet_socket_family(socket.family)
                    _utils.check_socket_is_connected(socket)
                except BaseException:
                    socket.close()
                    raise
                if ssl:
                    if server_hostname is None:
                        raise ValueError("You must set server_hostname when using ssl without a host")
                    socket_factory = _utils.make_callback(
                        self.__wrap_ssl_over_stream_socket_client_side,
                        backend,
                        socket,
                        ssl_context=ssl,
                        server_hostname=server_hostname,
                        ssl_handshake_timeout=ssl_handshake_timeout,
                        ssl_shutdown_timeout=ssl_shutdown_timeout,
                        ssl_standard_compatible=ssl_standard_compatible,
                        **kwargs,
                    )
                else:
                    socket_factory = _utils.make_callback(backend.wrap_stream_socket, socket, **kwargs)
            case (str(host), int(port)):
                if ssl:
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
                        if not host:
                            raise ValueError("You must set server_hostname when using ssl without a host")
                        server_hostname = host
                    socket_factory = _utils.make_callback(
                        self.__create_ssl_over_tcp_connection,
                        backend,
                        host,
                        port,
                        ssl_context=ssl,
                        server_hostname=server_hostname,
                        ssl_handshake_timeout=ssl_handshake_timeout,
                        ssl_shutdown_timeout=ssl_shutdown_timeout,
                        ssl_standard_compatible=ssl_standard_compatible,
                        **kwargs,
                    )
                else:
                    socket_factory = _utils.make_callback(backend.create_tcp_connection, host, port, **kwargs)
            case _:
                raise TypeError("Invalid arguments")

        self.__endpoint = _base.DeferredAsyncEndpointInit(
            backend=backend,
            endpoint_factory=_utils.make_callback(
                self.__create_endpoint,
                socket_factory,
                protocol=protocol,
                max_recv_size=max_recv_size,
            ),
        )

        self.__receive_lock: ILock = backend.create_lock()
        self.__send_lock: ILock = backend.create_fair_lock()

    @staticmethod
    async def __create_ssl_over_tcp_connection(
        backend: AsyncBackend,
        host: str,
        port: int,
        ssl_context: SSLContext,
        *,
        server_hostname: str | None,
        ssl_handshake_timeout: float | None,
        ssl_shutdown_timeout: float | None,
        ssl_standard_compatible: bool,
        local_address: tuple[str, int] | None = None,
        happy_eyeballs_delay: float | None = None,
    ) -> AsyncStreamTransport:
        from ..lowlevel.api_async.transports.tls import AsyncTLSStreamTransport

        transport = await backend.create_tcp_connection(
            host,
            port,
            local_address=local_address,
            happy_eyeballs_delay=happy_eyeballs_delay,
        )

        return await AsyncTLSStreamTransport.wrap(
            transport,
            ssl_context,
            server_side=False,
            handshake_timeout=ssl_handshake_timeout,
            shutdown_timeout=ssl_shutdown_timeout,
            server_hostname=server_hostname or None,
            standard_compatible=ssl_standard_compatible,
        )

    @staticmethod
    async def __wrap_ssl_over_stream_socket_client_side(
        backend: AsyncBackend,
        socket: _socket.socket,
        ssl_context: SSLContext,
        *,
        server_hostname: str,
        ssl_handshake_timeout: float | None,
        ssl_shutdown_timeout: float | None,
        ssl_standard_compatible: bool,
    ) -> AsyncStreamTransport:
        from ..lowlevel.api_async.transports.tls import AsyncTLSStreamTransport

        transport = await backend.wrap_stream_socket(socket)

        return await AsyncTLSStreamTransport.wrap(
            transport,
            ssl_context,
            server_side=False,
            handshake_timeout=ssl_handshake_timeout,
            shutdown_timeout=ssl_shutdown_timeout,
            server_hostname=server_hostname or None,
            standard_compatible=ssl_standard_compatible,
        )

    @staticmethod
    async def __create_endpoint(
        transport_factory: Callable[[], Awaitable[AsyncStreamTransport]],
        *,
        protocol: AnyStreamProtocolType[_T_SentPacket, _T_ReceivedPacket],
        max_recv_size: int,
    ) -> AsyncStreamEndpoint[_T_SentPacket, _T_ReceivedPacket]:
        transport = await transport_factory()
        socket = transport.extra(INETSocketAttribute.socket)

        _utils.check_inet_socket_family(socket.family)

        with contextlib.suppress(OSError):
            set_tcp_nodelay(socket, True)
        with contextlib.suppress(OSError):
            set_tcp_keepalive(socket, True)
        return AsyncStreamEndpoint(transport, protocol, max_recv_size=max_recv_size)

    def __del__(self, *, _warn: _utils.WarnCallback = warnings.warn) -> None:
        try:
            endpoint = self.__endpoint.get_endpoint_unchecked()
        except AttributeError:
            return
        if endpoint is not None and not endpoint.is_closing():
            msg = f"unclosed client {self!r} pointing to {endpoint!r} (and cannot be closed synchronously)"
            _warn(msg, ResourceWarning, source=self)

    def __repr__(self) -> str:
        try:
            endpoint = self.__endpoint.get_endpoint_unchecked()
        except AttributeError:
            endpoint = None
        if endpoint is None:
            return f"<{self.__class__.__name__} (partially initialized)>"
        return f"<{self.__class__.__name__} endpoint={endpoint!r}>"

    def is_connected(self) -> bool:
        """
        Checks if the client initialization is finished.

        See Also:
            :meth:`wait_connected` method.

        Returns:
            the client connection state.
        """
        return self.__endpoint.is_connected()

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
        await self.__endpoint.connect()

    def is_closing(self) -> bool:
        """
        Checks if the client is closed or in the process of being closed.

        If :data:`True`, all future operations on the client object will raise a :exc:`.ClientClosedError`.

        See Also:
            :meth:`aclose` method.

        Returns:
            the client state.
        """
        return self.__endpoint.is_closing()

    async def aclose(self) -> None:
        """
        Closes the client. Does not require task synchronization.

        Once that happens, all future operations on the client object will raise a :exc:`.ClientClosedError`.
        The remote end will receive no more data (after queued data is flushed).

        Warning:
            :meth:`aclose` performs a graceful close, waiting for the connection to close.

            If :meth:`aclose` is cancelled, the client is closed abruptly.

        Can be safely called multiple times.
        """
        async with contextlib.AsyncExitStack() as stack:
            try:
                await stack.enter_async_context(self.__send_lock)
            except self.backend().get_cancelled_exc_class():
                if not self.__endpoint.is_closing():
                    await aclose_forcefully(self.__endpoint)
                raise
            else:
                await self.__endpoint.aclose()

    async def send_packet(self, packet: _T_SentPacket) -> None:
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
            endpoint = await self.__endpoint.connect()
            with self.__convert_socket_error(endpoint=endpoint):
                await endpoint.send_packet(packet)
                _utils.check_real_socket_state(endpoint.extra(INETSocketAttribute.socket))

    async def send_eof(self) -> None:
        """
        Closes the write end of the stream after the buffered write data is flushed. Does not require task synchronization.

        Can be safely called multiple times.

        Raises:
            OSError: unrelated OS error occurred. You should check :attr:`OSError.errno`.
        """
        async with self.__send_lock:
            try:
                endpoint = await self.__endpoint.connect()
            except ClientClosedError:
                return
            with self.__convert_socket_error(endpoint=endpoint):
                await endpoint.send_eof()

    async def recv_packet(self) -> _T_ReceivedPacket:
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
            endpoint = await self.__endpoint.connect()
            with self.__convert_socket_error(endpoint=endpoint):
                return await endpoint.recv_packet()
            raise AssertionError("Expected code to be unreachable.")

    def get_local_address(self) -> SocketAddress:
        """
        Returns the local socket IP address.

        If :meth:`wait_connected` was not called, an :exc:`OSError` may occur.

        Raises:
            ClientClosedError: the client object is closed.
            OSError: unrelated OS error occurred. You should check :attr:`OSError.errno`.

        Returns:
            the client's local address.
        """
        endpoint = self.__endpoint.get_sync()
        local_address = endpoint.extra(INETSocketAttribute.sockname)
        address_family = endpoint.extra(INETSocketAttribute.family)
        return new_socket_address(local_address, address_family)

    def get_remote_address(self) -> SocketAddress:
        """
        Returns the remote socket IP address.

        If :meth:`wait_connected` was not called, an :exc:`OSError` may occur.

        Raises:
            ClientClosedError: the client object is closed.
            OSError: unrelated OS error occurred. You should check :attr:`OSError.errno`.

        Returns:
            the client's remote address.
        """
        endpoint = self.__endpoint.get_sync()
        remote_address = endpoint.extra(INETSocketAttribute.peername)
        address_family = endpoint.extra(INETSocketAttribute.family)
        return new_socket_address(remote_address, address_family)

    @_utils.inherit_doc(AbstractAsyncNetworkClient)
    def backend(self) -> AsyncBackend:
        return self.__backend

    @classmethod
    @contextlib.contextmanager
    def __convert_socket_error(cls, *, endpoint: AsyncStreamEndpoint[Any, Any] | None) -> Iterator[None]:
        try:
            yield
        except ConnectionError as exc:
            raise cls.__abort() from exc
        except _ssl_module.SSLError if _ssl_module else () as exc:
            if _utils.is_ssl_eof_error(exc):
                raise cls.__abort() from exc
            raise
        except OSError as exc:
            if exc.errno in constants.CLOSED_SOCKET_ERRNOS:
                if endpoint is not None and endpoint.is_closing():
                    # aclose() called while recv_packet() is awaiting...
                    raise cls.__closed() from exc
                exc.add_note("The socket file descriptor was closed unexpectedly.")
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
        if (socket_proxy := self.__socket_proxy) is not None:
            return socket_proxy

        try:
            endpoint = self.__endpoint.get_sync()
        except OSError:
            pass
        else:
            self.__socket_proxy = socket_proxy = SocketProxy(endpoint.extra(INETSocketAttribute.socket))
            return socket_proxy

        raise AttributeError("Socket not connected")
