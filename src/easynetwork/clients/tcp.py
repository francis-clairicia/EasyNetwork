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
"""TCP Network client implementation module."""

from __future__ import annotations

__all__ = ["TCPNetworkClient"]

import contextlib
import errno as _errno
import socket as _socket
import threading
import warnings
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, final, overload

try:
    import ssl
except ImportError:  # pragma: no cover
    _ssl_module = None
else:
    _ssl_module = ssl
    del ssl

from .._typevars import _T_ReceivedPacket, _T_SentPacket
from ..exceptions import ClientClosedError
from ..lowlevel import _lock, _utils, constants
from ..lowlevel.api_sync.endpoints.stream import StreamEndpoint
from ..lowlevel.api_sync.transports import socket as _transport_socket
from ..lowlevel.socket import (
    INETSocketAttribute,
    SocketAddress,
    SocketProxy,
    new_socket_address,
    set_tcp_keepalive,
    set_tcp_nodelay,
)
from ..protocol import AnyStreamProtocolType
from .abc import AbstractNetworkClient

if TYPE_CHECKING:
    from ssl import SSLContext


class TCPNetworkClient(AbstractNetworkClient[_T_SentPacket, _T_ReceivedPacket]):
    """
    A network client interface for TCP connections.
    """

    __slots__ = (
        "__endpoint",
        "__socket_proxy",
        "__send_lock",
        "__receive_lock",
    )

    @overload
    def __init__(
        self,
        address: tuple[str, int],
        /,
        protocol: AnyStreamProtocolType[_T_SentPacket, _T_ReceivedPacket],
        *,
        connect_timeout: float | None = ...,
        local_address: tuple[str, int] | None = ...,
        ssl: SSLContext | bool | None = ...,
        server_hostname: str | None = ...,
        ssl_handshake_timeout: float | None = ...,
        ssl_shutdown_timeout: float | None = ...,
        ssl_standard_compatible: bool | None = ...,
        max_recv_size: int | None = ...,
        retry_interval: float = ...,
    ) -> None: ...

    @overload
    def __init__(
        self,
        socket: _socket.socket,
        /,
        protocol: AnyStreamProtocolType[_T_SentPacket, _T_ReceivedPacket],
        *,
        ssl: SSLContext | bool | None = ...,
        server_hostname: str | None = ...,
        ssl_handshake_timeout: float | None = ...,
        ssl_shutdown_timeout: float | None = ...,
        ssl_standard_compatible: bool | None = ...,
        max_recv_size: int | None = ...,
        retry_interval: float = ...,
    ) -> None: ...

    def __init__(
        self,
        __arg: _socket.socket | tuple[str, int],
        /,
        protocol: AnyStreamProtocolType[_T_SentPacket, _T_ReceivedPacket],
        *,
        ssl: SSLContext | bool | None = None,
        server_hostname: str | None = None,
        ssl_handshake_timeout: float | None = None,
        ssl_shutdown_timeout: float | None = None,
        ssl_standard_compatible: bool | None = None,
        max_recv_size: int | None = None,
        retry_interval: float = 1.0,
        **kwargs: Any,
    ) -> None:
        """
        Common Parameters:
            protocol: The :term:`protocol object` to use.

        Connection Parameters:
            address: A pair of ``(host, port)`` for connection.
            connect_timeout: The connection timeout (in seconds).
            local_address: If given, is a ``(local_host, local_port)`` tuple used to bind the socket locally.

        Socket Parameters:
            socket: An already connected TCP :class:`socket.socket`. If `socket` is given,
                    none of `connect_timeout` and `local_address` should be specified.

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
            retry_interval: The maximum wait time to wait for a blocking operation before retrying.
                            Set it to :data:`math.inf` to disable this feature.

        See Also:
            :ref:`SSL/TLS security considerations <ssl-security>`
        """
        super().__init__()

        from ..lowlevel._stream import _check_any_protocol

        _check_any_protocol(protocol)

        if max_recv_size is None:
            max_recv_size = constants.DEFAULT_STREAM_BUFSIZE

        if server_hostname is not None and not ssl:
            raise ValueError("server_hostname is only meaningful with ssl")

        if ssl_handshake_timeout is not None and not ssl:
            raise ValueError("ssl_handshake_timeout is only meaningful with ssl")

        if ssl_shutdown_timeout is not None and not ssl:
            raise ValueError("ssl_shutdown_timeout is only meaningful with ssl")

        if ssl_standard_compatible is not None and not ssl:
            raise ValueError("ssl_standard_compatible is only meaningful with ssl")

        if ssl_standard_compatible is None:
            ssl_standard_compatible = True

        socket: _socket.socket
        match __arg:
            case _socket.socket() if server_hostname is None and ssl:
                raise ValueError("You must set server_hostname when using ssl without a host")
            case _socket.socket() as socket if not kwargs:
                pass
            case (str(host), int(port)):
                if server_hostname is None and ssl:
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
                _utils.replace_kwargs(kwargs, {"local_address": "source_address", "connect_timeout": "timeout"})
                kwargs.setdefault("timeout", None)
                socket = _socket.create_connection((host, port), **kwargs, all_errors=True)
            case _:
                raise TypeError("Invalid arguments")

        try:
            _utils.check_inet_socket_family(socket.family)
            _utils.check_socket_is_connected(socket)

            transport: _transport_socket.SocketStreamTransport | _transport_socket.SSLStreamTransport

            if ssl:
                if _ssl_module is None:
                    raise RuntimeError("stdlib ssl module not available")

                if isinstance(ssl, bool):
                    ssl = _ssl_module.create_default_context()
                    assert isinstance(ssl, _ssl_module.SSLContext)  # nosec assert_used
                    if not server_hostname:
                        ssl.check_hostname = False
                    with contextlib.suppress(AttributeError):
                        ssl.options &= ~_ssl_module.OP_IGNORE_UNEXPECTED_EOF
                if not server_hostname:
                    server_hostname = None

                with self.__convert_socket_error(endpoint=None):
                    transport = _transport_socket.SSLStreamTransport(
                        socket,
                        ssl_context=ssl,
                        retry_interval=retry_interval,
                        server_hostname=server_hostname,
                        server_side=False,
                        standard_compatible=ssl_standard_compatible,
                        handshake_timeout=ssl_handshake_timeout,
                        shutdown_timeout=ssl_shutdown_timeout,
                    )

            else:
                transport = _transport_socket.SocketStreamTransport(socket, retry_interval=retry_interval)
        except BaseException:
            socket.close()
            raise
        finally:
            del socket

        self.__send_lock = _lock.ForkSafeLock(threading.Lock)
        self.__receive_lock = _lock.ForkSafeLock(threading.Lock)

        try:
            self.__endpoint = StreamEndpoint(
                transport,
                protocol,
                max_recv_size=max_recv_size,
            )
            self.__socket_proxy = SocketProxy(transport.extra(INETSocketAttribute.socket), lock=self.__send_lock.get)

            with contextlib.suppress(OSError):
                set_tcp_nodelay(self.socket, True)
            with contextlib.suppress(OSError):
                set_tcp_keepalive(self.socket, True)
        except BaseException:
            transport.close()
            raise

    def __del__(self, *, _warn: _utils.WarnCallback = warnings.warn) -> None:
        try:
            endpoint = self.__endpoint
        except AttributeError:
            return
        if not endpoint.is_closed():
            _warn(f"unclosed client {self!r}", ResourceWarning, source=self)
            endpoint.close()

    def __repr__(self) -> str:
        try:
            return f"<{self.__class__.__name__} endpoint={self.__endpoint!r}>"
        except AttributeError:
            return f"<{self.__class__.__name__} (partially initialized)>"

    def is_closed(self) -> bool:
        """
        Checks if the client is in a closed state. Thread-safe.

        If :data:`True`, all future operations on the client object will raise a :exc:`.ClientClosedError`.

        Returns:
            the client state.
        """
        with self.__send_lock.get():
            return self.__endpoint.is_closed()

    def close(self) -> None:
        """
        Close the client. Thread-safe.

        Once that happens, all future operations on the client object will raise a :exc:`.ClientClosedError`.
        The remote end will receive no more data (after queued data is flushed).

        Can be safely called multiple times.
        """
        with self.__send_lock.get():
            self.__endpoint.close()

    def send_packet(self, packet: _T_SentPacket, *, timeout: float | None = None) -> None:
        """
        Sends `packet` to the remote endpoint. Thread-safe.

        If `timeout` is not :data:`None`, the entire send operation will take at most `timeout` seconds.

        Warning:
            A timeout on a send operation is unusual unless you have a SSL/TLS context.

            In the case of a timeout, it is impossible to know if all the packet data has been sent.
            This would leave the connection in an inconsistent state.

        Important:
            The lock acquisition time is included in the `timeout`.

            This means that you may get a :exc:`TimeoutError` because it took too long to get the lock.

        Parameters:
            packet: the Python object to send.
            timeout: the allowed time (in seconds) for blocking operations.

        Raises:
            ClientClosedError: the client object is closed.
            ConnectionError: connection unexpectedly closed during operation.
                             You should not attempt any further operation and close the client object.
            TimeoutError: the send operation does not end up after `timeout` seconds.
            OSError: unrelated OS error occurred. You should check :attr:`OSError.errno`.
            RuntimeError: :meth:`send_eof` has been called earlier.
        """
        with _utils.lock_with_timeout(self.__send_lock.get(), timeout) as timeout:
            endpoint = self.__endpoint
            if endpoint.is_closed():
                raise self.__closed()
            with self.__convert_socket_error(endpoint=endpoint):
                endpoint.send_packet(packet, timeout=timeout)
                _utils.check_real_socket_state(endpoint.extra(INETSocketAttribute.socket))

    def send_eof(self) -> None:
        """
        Close the write end of the stream after the buffered write data is flushed. Thread-safe.

        This method does nothing if the client is closed.

        Can be safely called multiple times.

        Raises:
            OSError: unrelated OS error occurred. You should check :attr:`OSError.errno`.
        """
        with self.__send_lock.get():
            endpoint = self.__endpoint
            if endpoint.is_closed():
                return
            with self.__convert_socket_error(endpoint=endpoint):
                endpoint.send_eof()

    def recv_packet(self, *, timeout: float | None = None) -> _T_ReceivedPacket:
        """
        Waits for a new packet to arrive from the remote endpoint. Thread-safe.

        If `timeout` is not :data:`None`, the entire receive operation will take at most `timeout` seconds.

        Important:
            The lock acquisition time is included in the `timeout`.

            This means that you may get a :exc:`TimeoutError` because it took too long to get the lock.

        Parameters:
            timeout: the allowed time (in seconds) for blocking operations.

        Raises:
            ClientClosedError: the client object is closed.
            ConnectionError: connection unexpectedly closed during operation.
                             You should not attempt any further operation and close the client object.
            TimeoutError: the receive operation does not end up after `timeout` seconds.
            OSError: unrelated OS error occurred. You should check :attr:`OSError.errno`.
            StreamProtocolParseError: invalid data received.

        Returns:
            the received packet.
        """
        with _utils.lock_with_timeout(self.__receive_lock.get(), timeout) as timeout:
            endpoint = self.__endpoint
            if endpoint.is_closed():
                raise self.__closed()
            with self.__convert_socket_error(endpoint=endpoint):
                return endpoint.recv_packet(timeout=timeout)
            raise AssertionError("Expected code to be unreachable.")

    @classmethod
    @contextlib.contextmanager
    def __convert_socket_error(cls, *, endpoint: StreamEndpoint[Any, Any] | None) -> Iterator[None]:
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
                if endpoint is not None and endpoint.is_closed():
                    # close() called while recv_packet() is awaiting...
                    raise cls.__closed() from exc
                exc.add_note("The socket file descriptor was closed unexpectedly.")
            raise

    @staticmethod
    def __abort() -> OSError:
        return _utils.error_from_errno(_errno.ECONNABORTED)

    @staticmethod
    def __closed() -> ClientClosedError:
        return ClientClosedError("Closed client")

    def get_local_address(self) -> SocketAddress:
        """
        Returns the local socket IP address. Thread-safe.

        Raises:
            ClientClosedError: the client object is closed.
            OSError: unrelated OS error occurred. You should check :attr:`OSError.errno`.

        Returns:
            the client's local address.
        """
        with self.__send_lock.get():
            endpoint = self.__endpoint
            if endpoint.is_closed():
                raise self.__closed()
            local_address = endpoint.extra(INETSocketAttribute.sockname)
            address_family = endpoint.extra(INETSocketAttribute.family)
            return new_socket_address(local_address, address_family)

    def get_remote_address(self) -> SocketAddress:
        """
        Returns the remote socket IP address. Thread-safe.

        Raises:
            ClientClosedError: the client object is closed.
            OSError: unrelated OS error occurred. You should check :attr:`OSError.errno`.

        Returns:
            the client's remote address.
        """
        with self.__send_lock.get():
            endpoint = self.__endpoint
            if endpoint.is_closed():
                raise self.__closed()
            remote_address = endpoint.extra(INETSocketAttribute.peername)
            address_family = endpoint.extra(INETSocketAttribute.family)
            return new_socket_address(remote_address, address_family)

    def fileno(self) -> int:
        """
        Returns the socket's file descriptor, or ``-1`` if the client (or the socket) is closed. Thread-safe.

        Returns:
            the opened file descriptor.
        """
        return self.socket.fileno()

    @property
    @final
    def socket(self) -> SocketProxy:
        """A view to the underlying socket instance. Read-only attribute."""
        return self.__socket_proxy
