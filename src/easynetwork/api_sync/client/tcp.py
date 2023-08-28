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
"""TCP Network client implementation module"""

from __future__ import annotations

__all__ = ["TCPNetworkClient"]

import contextlib as _contextlib
import errno as _errno
import math
import socket as _socket
import threading
import time
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING, Any, NoReturn, TypeGuard, final, overload

try:
    import ssl
except ImportError:  # pragma: no cover
    _ssl_module = None
else:
    _ssl_module = ssl
    del ssl

from ..._typevars import _ReceivedPacketT, _SentPacketT
from ...exceptions import ClientClosedError
from ...protocol import StreamProtocol
from ...tools._lock import ForkSafeLock
from ...tools._stream import StreamDataConsumer
from ...tools._utils import (
    check_real_socket_state as _check_real_socket_state,
    check_socket_family as _check_socket_family,
    check_socket_no_ssl as _check_socket_no_ssl,
    error_from_errno as _error_from_errno,
    is_ssl_eof_error as _is_ssl_eof_error,
    lock_with_timeout as _lock_with_timeout,
    replace_kwargs as _replace_kwargs,
    retry_socket_method as _retry_socket_method,
    retry_ssl_socket_method as _retry_ssl_socket_method,
    validate_timeout_delay as _validate_timeout_delay,
)
from ...tools.constants import CLOSED_SOCKET_ERRNOS, MAX_STREAM_BUFSIZE, SSL_HANDSHAKE_TIMEOUT, SSL_SHUTDOWN_TIMEOUT
from ...tools.socket import SocketAddress, SocketProxy, new_socket_address, set_tcp_keepalive, set_tcp_nodelay
from .abc import AbstractNetworkClient

if TYPE_CHECKING:
    import ssl as _typing_ssl


class TCPNetworkClient(AbstractNetworkClient[_SentPacketT, _ReceivedPacketT]):
    """
    A network client interface for TCP connections.
    """

    __slots__ = (
        "__socket",
        "__over_ssl",
        "__socket_proxy",
        "__send_lock",
        "__receive_lock",
        "__socket_lock",
        "__producer",
        "__consumer",
        "__addr",
        "__peer",
        "__eof_reached",
        "__eof_sent",
        "__last_ssl_eof_error",
        "__max_recv_size",
        "__retry_interval",
        "__ssl_shutdown_timeout",
    )

    @overload
    def __init__(
        self,
        address: tuple[str, int],
        /,
        protocol: StreamProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        connect_timeout: float | None = ...,
        local_address: tuple[str, int] | None = ...,
        ssl: _typing_ssl.SSLContext | bool | None = ...,
        server_hostname: str | None = ...,
        ssl_handshake_timeout: float | None = ...,
        ssl_shutdown_timeout: float | None = ...,
        ssl_shared_lock: bool | None = ...,
        max_recv_size: int | None = ...,
        retry_interval: float = ...,
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
        retry_interval: float = ...,
    ) -> None:
        ...

    def __init__(
        self,
        __arg: _socket.socket | tuple[str, int],
        /,
        protocol: StreamProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        ssl: _typing_ssl.SSLContext | bool | None = None,
        server_hostname: str | None = None,
        ssl_handshake_timeout: float | None = None,
        ssl_shutdown_timeout: float | None = None,
        ssl_shared_lock: bool | None = None,
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
            ssl_shared_lock: If :data:`True` (the default), :meth:`send_packet` and :meth:`recv_packet` uses
                             the same lock instance.
            max_recv_size: Read buffer size. If not given, a default reasonable value is used.
            retry_interval: The maximum wait time to wait for a blocking operation before retrying.
                            Set it to :data:`math.inf` to disable this feature.

        See Also:
            :ref:`SSL/TLS security considerations <ssl-security>`
        """
        self.__socket: _socket.socket | None = None  # If any exception occurs, the client will already be in a closed state
        super().__init__()

        if not isinstance(protocol, StreamProtocol):
            raise TypeError(f"Expected a StreamProtocol object, got {protocol!r}")
        self.__consumer: StreamDataConsumer[_ReceivedPacketT] = StreamDataConsumer(protocol)
        self.__producer: Callable[[_SentPacketT], Iterator[bytes]] = protocol.generate_chunks

        if max_recv_size is None:
            max_recv_size = MAX_STREAM_BUFSIZE
        if not isinstance(max_recv_size, int) or max_recv_size <= 0:
            raise ValueError("'max_recv_size' must be a strictly positive integer")
        self.__max_recv_size: int = max_recv_size

        self.__retry_interval: float | None
        self.__retry_interval = retry_interval = _validate_timeout_delay(float(retry_interval), positive_check=False)
        if self.__retry_interval <= 0:
            raise ValueError("retry_interval must be a strictly positive float")
        if math.isinf(self.__retry_interval):
            self.__retry_interval = None

        if server_hostname is not None and not ssl:
            raise ValueError("server_hostname is only meaningful with ssl")

        if ssl_handshake_timeout is not None and not ssl:
            raise ValueError("ssl_handshake_timeout is only meaningful with ssl")

        if ssl_shutdown_timeout is not None and not ssl:
            raise ValueError("ssl_shutdown_timeout is only meaningful with ssl")

        if ssl_shared_lock is not None and not ssl:
            raise ValueError("ssl_shared_lock is only meaningful with ssl")

        if ssl_shared_lock is None:
            ssl_shared_lock = True

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
                _replace_kwargs(kwargs, {"local_address": "source_address", "connect_timeout": "timeout"})
                kwargs.setdefault("timeout", None)
                socket = _socket.create_connection((host, port), **kwargs, all_errors=True)
            case _:  # pragma: no cover
                raise TypeError("Invalid arguments")

        try:
            if socket.type != _socket.SOCK_STREAM:
                raise ValueError("Invalid socket type")

            _check_socket_family(socket.family)
            _check_socket_no_ssl(socket)

            # Do not use global default timeout here
            socket.settimeout(0)

            self.__addr: SocketAddress = new_socket_address(socket.getsockname(), socket.family)
            self.__peer: SocketAddress = new_socket_address(socket.getpeername(), socket.family)
            self.__over_ssl: bool = False
            self.__eof_reached: bool = False
            self.__eof_sent: bool = False
            self.__last_ssl_eof_error: Exception | None = None

            if ssl:
                if _ssl_module is None:
                    raise RuntimeError("stdlib ssl module not available")

                ssl_context: _typing_ssl.SSLContext
                if isinstance(ssl, bool):
                    ssl_context = _ssl_module.create_default_context()
                    if not server_hostname:
                        ssl_context.check_hostname = False
                    if hasattr(_ssl_module, "OP_IGNORE_UNEXPECTED_EOF"):
                        ssl_context.options &= ~getattr(_ssl_module, "OP_IGNORE_UNEXPECTED_EOF")
                else:
                    ssl_context = ssl
                if not server_hostname:
                    server_hostname = None
                socket = ssl_context.wrap_socket(
                    socket,
                    server_side=False,
                    do_handshake_on_connect=False,
                    suppress_ragged_eofs=False,
                    server_hostname=server_hostname,
                )

                self.__over_ssl = True

                if ssl_handshake_timeout is None:
                    ssl_handshake_timeout = SSL_HANDSHAKE_TIMEOUT

                with self.__convert_socket_error():
                    _retry_ssl_socket_method(socket, ssl_handshake_timeout, retry_interval, socket.do_handshake, block=False)

                if ssl_shutdown_timeout is None:
                    ssl_shutdown_timeout = SSL_SHUTDOWN_TIMEOUT

            assert ssl_shared_lock is not None  # nosec assert_used
            self.__send_lock: ForkSafeLock[threading.Lock]
            self.__receive_lock: ForkSafeLock[threading.Lock]
            if self.__over_ssl and ssl_shared_lock:
                self.__send_lock = self.__receive_lock = ForkSafeLock(threading.Lock)
            else:
                self.__send_lock = ForkSafeLock(threading.Lock)
                self.__receive_lock = ForkSafeLock(threading.Lock)
            self.__socket_lock: ForkSafeLock[threading.Lock] = ForkSafeLock(threading.Lock)

            with _contextlib.suppress(OSError):
                set_tcp_nodelay(socket, True)
            with _contextlib.suppress(OSError):
                set_tcp_keepalive(socket, True)

            self.__socket_proxy = SocketProxy(socket, lock=self.__socket_lock.get)
            self.__ssl_shutdown_timeout: float | None = ssl_shutdown_timeout
        except BaseException:
            socket.close()
            raise

        self.__socket = socket  # There was no errors

    def __del__(self) -> None:  # pragma: no cover
        try:
            socket: _socket.socket | None = self.__socket
        except AttributeError:
            return
        if socket is not None:
            socket.close()

    def __repr__(self) -> str:
        socket = self.__socket
        if socket is None:
            return f"<{type(self).__name__} closed>"
        return f"<{type(self).__name__} socket={socket!r}>"

    def is_closed(self) -> bool:
        """
        Checks if the client is in a closed state. Thread-safe.

        If :data:`True`, all future operations on the client object will raise a :exc:`.ClientClosedError`.

        Returns:
            the client state.
        """
        with self.__socket_lock.get():
            return self.__socket is None

    def close(self) -> None:
        """
        Close the client. Thread-safe.

        Once that happens, all future operations on the client object will raise a :exc:`.ClientClosedError`.
        The remote end will receive no more data (after queued data is flushed).

        Can be safely called multiple times.

        Raises:
            OSError: Unrelated OS error happen. You should check :attr:`OSError.errno`.
        """
        with self.__send_lock.get(), self.__socket_lock.get():
            self.__last_ssl_eof_error = None
            if (socket := self.__socket) is None:
                return
            self.__socket = None
            try:
                if not self.__eof_reached and self.__is_ssl_socket(socket):
                    with self.__convert_socket_error(), _contextlib.suppress(TimeoutError):
                        retry_interval: float | None = self.__retry_interval
                        socket = _retry_ssl_socket_method(socket, self.__ssl_shutdown_timeout, retry_interval, socket.unwrap)
            except ConnectionError:
                # It is normal if there was connection errors during operations. But do not propagate this exception,
                # as we will never reuse this socket
                pass
            finally:
                try:
                    socket.shutdown(_socket.SHUT_RDWR)
                except OSError:
                    # On macOS, an OSError is raised if there is no connection
                    pass
                finally:
                    socket.close()

    def send_packet(self, packet: _SentPacketT, *, timeout: float | None = None) -> None:
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

        Arguments:
            packet: the Python object to send.
            timeout: the allowed time (in seconds) for blocking operations.

        Raises:
            ClientClosedError: the client object is closed.
            ConnectionError: connection unexpectedly closed during operation.
                             You should not attempt any further operation and close the client object.
            TimeoutError: the send operation does not end up after `timeout` seconds.
            OSError: Unrelated OS error happen. You should check :attr:`OSError.errno`.
            RuntimeError: :meth:`send_eof` has been called earlier.
        """
        with _lock_with_timeout(self.__send_lock.get(), timeout, error_message="send_packet() timed out") as timeout:
            socket = self.__ensure_connected()
            if self.__eof_sent:
                raise RuntimeError("send_eof() has been called earlier")
            if self.__over_ssl and self.__eof_reached:
                self.__abort_eof()

            data: bytes = b"".join(self.__producer(packet))
            buffer = memoryview(data)
            perf_counter = time.perf_counter  # pull function to local namespace
            retry_interval: float | None = self.__retry_interval
            try:
                remaining: int = buffer.nbytes
                with self.__convert_socket_error():
                    while remaining > 0:
                        sent: int
                        try:
                            _start = perf_counter()
                            if self.__is_ssl_socket(socket):
                                sent = _retry_ssl_socket_method(socket, timeout, retry_interval, socket.send, buffer)
                            else:
                                sent = _retry_socket_method(socket, timeout, retry_interval, "write", socket.send, buffer)
                            _end = perf_counter()
                        except TimeoutError:
                            raise TimeoutError("send_packet() timed out") from None
                        remaining -= sent
                        buffer = buffer[sent:]
                        if timeout is not None:
                            timeout -= _end - _start
                    _check_real_socket_state(socket)
            finally:
                del buffer, data

    def send_eof(self) -> None:
        """
        Close the write end of the stream after the buffered write data is flushed. Thread-safe.

        Can be safely called multiple times.

        Raises:
            ClientClosedError: the client object is closed.
            OSError: Unrelated OS error happen. You should check :attr:`OSError.errno`.
            NotImplementedError: SSL/TLS API does not support sending EOF.
        """
        if self.__over_ssl:
            # ssl.SSLSocket.shutdown() would shutdown both read and write streams
            raise NotImplementedError("SSL/TLS API does not support sending EOF.")

        with self.__send_lock.get(), self.__socket_lock.get():
            if self.__eof_sent:
                return
            self.__eof_sent = True
            if (socket := self.__socket) is not None:
                socket.shutdown(_socket.SHUT_WR)

    def recv_packet(self, *, timeout: float | None = None) -> _ReceivedPacketT:
        """
        Waits for a new packet to arrive from the remote endpoint. Thread-safe.

        If `timeout` is not :data:`None`, the entire receive operation will take at most `timeout` seconds.

        Important:
            The lock acquisition time is included in the `timeout`.

            This means that you may get a :exc:`TimeoutError` because it took too long to get the lock.

        Arguments:
            timeout: the allowed time (in seconds) for blocking operations.

        Raises:
            ClientClosedError: the client object is closed.
            ConnectionError: connection unexpectedly closed during operation.
                             You should not attempt any further operation and close the client object.
            TimeoutError: the receive operation does not end up after `timeout` seconds.
            OSError: Unrelated OS error happen. You should check :attr:`OSError.errno`.

        Returns:
            the received packet.
        """
        with _lock_with_timeout(self.__receive_lock.get(), timeout, error_message="recv_packet() timed out") as timeout:
            consumer = self.__consumer
            try:
                return next(consumer)  # If there is enough data from last call to create a packet, return immediately
            except StopIteration:
                pass

            socket = self.__ensure_connected()
            if self.__eof_reached:
                self.__abort_eof()

            bufsize: int = self.__max_recv_size
            perf_counter = time.perf_counter  # pull function to local namespace
            retry_interval: float | None = self.__retry_interval

            while True:
                with self.__convert_socket_error():
                    try:
                        _start = perf_counter()
                        chunk: bytes
                        if self.__is_ssl_socket(socket):
                            chunk = _retry_ssl_socket_method(socket, timeout, retry_interval, socket.recv, bufsize)
                        else:
                            chunk = _retry_socket_method(socket, timeout, retry_interval, "read", socket.recv, bufsize)
                        _end = perf_counter()
                    except TimeoutError:
                        break
                try:
                    if not chunk:
                        self.__eof_reached = True
                        self.__abort_eof()
                    buffer_not_full: bool = len(chunk) < bufsize
                    consumer.feed(chunk)
                finally:
                    del chunk
                try:
                    return next(consumer)
                except StopIteration:
                    if timeout is not None:
                        if timeout > 0:
                            timeout -= _end - _start
                        elif buffer_not_full:
                            break
                    continue
            # Loop break
            raise TimeoutError("recv_packet() timed out")

    def __ensure_connected(self) -> _socket.socket:
        if (socket := self.__socket) is None:
            raise ClientClosedError("Closed client")
        return socket

    @_contextlib.contextmanager
    def __convert_socket_error(self) -> Iterator[None]:
        try:
            with self.__convert_ssl_eof_error():
                yield
        except ConnectionError as exc:
            self.__abort(exc)
        except OSError as exc:
            if exc.errno in CLOSED_SOCKET_ERRNOS:
                self.__abort(exc)
            raise

    @_contextlib.contextmanager
    def __convert_ssl_eof_error(self) -> Iterator[None]:
        if _ssl_module is None:
            yield
            return
        try:
            yield
        except _ssl_module.SSLError as exc:
            if isinstance(exc, _ssl_module.SSLZeroReturnError) or _is_ssl_eof_error(exc):
                exc = exc.with_traceback(None)
                exc.__context__ = exc.__cause__ = None
                self.__eof_reached = True
                self.__last_ssl_eof_error = exc
                self.__abort(exc)
            raise

    @staticmethod
    def __abort(cause: BaseException | None) -> NoReturn:
        if cause is None:
            raise _error_from_errno(_errno.ECONNABORTED)
        raise _error_from_errno(_errno.ECONNABORTED) from cause

    def __abort_eof(self) -> NoReturn:
        if self.__over_ssl:
            self.__abort(self.__last_ssl_eof_error)
        else:
            self.__abort(None)

    def get_local_address(self) -> SocketAddress:
        """
        Returns the local socket IP address. Thread-safe.

        Raises:
            ClientClosedError: the client object is closed.
            OSError: Unrelated OS error happen. You should check :attr:`OSError.errno`.

        Returns:
            the client's local address.
        """
        return self.__addr

    def get_remote_address(self) -> SocketAddress:
        """
        Returns the remote socket IP address. Thread-safe.

        Raises:
            ClientClosedError: the client object is closed.
            OSError: Unrelated OS error happen. You should check :attr:`OSError.errno`.

        Returns:
            the client's remote address.
        """
        return self.__peer

    def fileno(self) -> int:
        """
        Returns the socket's file descriptor, or ``-1`` if the client (or the socket) is closed. Thread-safe.

        Returns:
            the opened file descriptor.
        """
        with self.__socket_lock.get():
            if (socket := self.__socket) is None:
                return -1
            return socket.fileno()

    def __is_ssl_socket(self, socket: _socket.socket) -> TypeGuard[_typing_ssl.SSLSocket]:
        # Optimization: Instead of always do a isinstance(), do it once then use the TypeGuard to cast the socket type
        # for static type checkers
        return self.__over_ssl

    @property
    @final
    def socket(self) -> SocketProxy:
        """A view to the underlying socket instance. Read-only attribute."""
        return self.__socket_proxy

    @property
    @final
    def max_recv_size(self) -> int:
        """Read buffer size. Read-only attribute."""
        return self.__max_recv_size
