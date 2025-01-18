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
"""Transport implementations module wrapping sockets."""

from __future__ import annotations

__all__ = [
    "SSLStreamTransport",
    "SocketDatagramTransport",
    "SocketStreamTransport",
]

import errno
import itertools
import selectors
import socket
import warnings
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, ParamSpec, TypeVar

try:
    import ssl
except ImportError:  # pragma: no cover
    _ssl_module = None
else:
    _ssl_module = ssl
    del ssl

from ....exceptions import UnsupportedOperation
from ... import _utils, constants, socket as socket_tools
from . import base_selector

if TYPE_CHECKING:
    from ssl import SSLContext, SSLSession, SSLSocket

    from _typeshed import WriteableBuffer

_P = ParamSpec("_P")
_T_Return = TypeVar("_T_Return")


def _close_stream_socket(sock: socket.socket) -> None:
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    finally:
        sock.close()


class SocketStreamTransport(base_selector.SelectorStreamTransport):
    """
    A stream data transport implementation which wraps a stream :class:`~socket.socket`.
    """

    __slots__ = ("__socket", "__extra_attributes")

    def __init__(
        self,
        sock: socket.socket,
        retry_interval: float,
        *,
        selector_factory: Callable[[], selectors.BaseSelector] | None = None,
    ) -> None:
        """
        Parameters:
            sock: The :data:`~socket.SOCK_STREAM` socket to wrap.
            retry_interval: The maximum wait time to wait for a blocking operation before retrying.
                            Set it to :data:`math.inf` to disable this feature.
            selector_factory: If given, the callable object to use to create a new :class:`selectors.BaseSelector` instance.
        """
        super().__init__(retry_interval=retry_interval, selector_factory=selector_factory)

        _utils.check_socket_no_ssl(sock)
        if sock.type != socket.SOCK_STREAM:
            raise ValueError("A 'SOCK_STREAM' socket is expected")
        self.__socket: socket.socket = sock
        self.__socket.setblocking(False)

        self.__extra_attributes = MappingProxyType(socket_tools._get_socket_extra(self.__socket))

    def __del__(self, *, _warn: _utils.WarnCallback = warnings.warn) -> None:
        try:
            sock: socket.socket = self.__socket
        except AttributeError:
            return
        if sock.fileno() >= 0:
            _warn(f"unclosed transport {self!r}", ResourceWarning, source=self)
            sock.close()

    @_utils.inherit_doc(base_selector.SelectorStreamTransport)
    def is_closed(self) -> bool:
        return self.__socket.fileno() < 0

    @_utils.inherit_doc(base_selector.SelectorStreamTransport)
    def close(self) -> None:
        _close_stream_socket(self.__socket)

    @_utils.inherit_doc(base_selector.SelectorStreamTransport)
    def recv_noblock(self, bufsize: int) -> bytes:
        try:
            return self.__socket.recv(bufsize)
        except (BlockingIOError, InterruptedError):
            raise base_selector.WouldBlockOnRead(self.__socket.fileno()) from None

    @_utils.inherit_doc(base_selector.SelectorStreamTransport)
    def recv_noblock_into(self, buffer: WriteableBuffer) -> int:
        try:
            return self.__socket.recv_into(buffer)
        except (BlockingIOError, InterruptedError):
            raise base_selector.WouldBlockOnRead(self.__socket.fileno()) from None

    @_utils.inherit_doc(base_selector.SelectorStreamTransport)
    def send_noblock(self, data: bytes | bytearray | memoryview) -> int:
        try:
            return self.__socket.send(data)
        except (BlockingIOError, InterruptedError):
            raise base_selector.WouldBlockOnWrite(self.__socket.fileno()) from None

    @_utils.inherit_doc(base_selector.SelectorStreamTransport)
    def send_all_from_iterable(self, iterable_of_data: Iterable[bytes | bytearray | memoryview], timeout: float) -> None:
        if constants.SC_IOV_MAX <= 0:
            return super().send_all_from_iterable(iterable_of_data, timeout)

        socket = self.__socket
        socket_fileno = self.__socket.fileno
        if not _utils.supports_socket_sendmsg(socket):
            return super().send_all_from_iterable(iterable_of_data, timeout)

        buffers: deque[memoryview] = deque(map(memoryview, iterable_of_data))  # type: ignore[arg-type]
        del iterable_of_data

        def try_sendmsg() -> int:
            try:
                return socket.sendmsg(itertools.islice(buffers, constants.SC_IOV_MAX))
            except (BlockingIOError, InterruptedError):
                raise base_selector.WouldBlockOnWrite(socket_fileno()) from None

        while buffers:
            sent, timeout = self._retry(try_sendmsg, timeout)
            _utils.adjust_leftover_buffer(buffers, sent)

    @_utils.inherit_doc(base_selector.SelectorStreamTransport)
    def send_eof(self) -> None:
        if self.__socket.fileno() < 0:
            return
        try:
            self.__socket.shutdown(socket.SHUT_WR)
        except OSError as exc:
            if exc.errno in constants.NOT_CONNECTED_SOCKET_ERRNOS:
                # On some platforms (e.g. macOS), shutdown() raises if the socket is already disconnected.
                pass
            elif exc.errno in constants.CLOSED_SOCKET_ERRNOS:
                pass
            else:
                raise

    @property
    @_utils.inherit_doc(base_selector.SelectorStreamTransport)
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__extra_attributes


class SSLStreamTransport(base_selector.SelectorStreamTransport):
    """
    A stream data transport implementation which wraps a stream :class:`~socket.socket`.
    """

    __slots__ = ("__socket", "__ssl_shutdown_timeout", "__standard_compatible", "__extra_attributes")

    def __init__(
        self,
        sock: socket.socket,
        ssl_context: SSLContext,
        retry_interval: float,
        *,
        handshake_timeout: float | None = None,
        shutdown_timeout: float | None = None,
        server_side: bool | None = None,
        server_hostname: str | None = None,
        standard_compatible: bool = True,
        session: SSLSession | None = None,
        selector_factory: Callable[[], selectors.BaseSelector] | None = None,
    ) -> None:
        """
        Parameters:
            sock: The :data:`~socket.SOCK_STREAM` socket to wrap.
            ssl_context: a :class:`ssl.SSLContext` object to use to create the transport.
            retry_interval: The maximum wait time to wait for a blocking operation before retrying.
                            Set it to :data:`math.inf` to disable this feature.
            handshake_timeout: The time in seconds to wait for the TLS handshake to complete before aborting the connection.
                               ``60.0`` seconds if :data:`None` (default).
            shutdown_timeout: The time in seconds to wait for the SSL shutdown to complete before aborting the connection.
                              ``30.0`` seconds if :data:`None` (default).
            server_side: Indicates whether we are a client or a server for the handshake part. If it is set to :data:`None`,
                         it is deduced according to `server_hostname`.
            server_hostname: sets or overrides the hostname that the target server's certificate will be matched against.
                             If `server_side` is :data:`True`, you must pass a value for `server_hostname`.
            standard_compatible: If :data:`False`, skip the closing handshake when closing the connection,
                                 and don't raise an exception if the peer does the same.
            session: If an SSL session already exits, use it insead.
            selector_factory: If given, the callable object to use to create a new :class:`selectors.BaseSelector` instance.
        """
        super().__init__(retry_interval=retry_interval, selector_factory=selector_factory)

        if handshake_timeout is None:
            handshake_timeout = constants.SSL_HANDSHAKE_TIMEOUT
        if shutdown_timeout is None:
            shutdown_timeout = constants.SSL_SHUTDOWN_TIMEOUT

        handshake_timeout = _utils.validate_timeout_delay(handshake_timeout, positive_check=True)
        shutdown_timeout = _utils.validate_timeout_delay(shutdown_timeout, positive_check=True)
        standard_compatible = bool(standard_compatible)

        _utils.check_socket_no_ssl(sock)
        if sock.type != socket.SOCK_STREAM:
            raise ValueError("A 'SOCK_STREAM' socket is expected")
        if server_side is None:
            server_side = not server_hostname
        self.__socket: SSLSocket = ssl_context.wrap_socket(
            sock,
            server_side=server_side,
            server_hostname=server_hostname,
            suppress_ragged_eofs=not standard_compatible,
            do_handshake_on_connect=False,
            session=session,
        )
        self.__socket.setblocking(False)

        try:
            self._retry(lambda: self._try_ssl_method(self.__socket.do_handshake), handshake_timeout)
        except BaseException:
            self.__socket.close()
            raise

        self.__ssl_shutdown_timeout: float = shutdown_timeout
        self.__standard_compatible: bool = standard_compatible

        self.__extra_attributes = MappingProxyType(
            {
                **socket_tools._get_socket_extra(self.__socket),
                **socket_tools._get_tls_extra(self.__socket, self.__standard_compatible),
            }
        )

    def __del__(self, *, _warn: _utils.WarnCallback = warnings.warn) -> None:
        try:
            sock: socket.socket = self.__socket
        except AttributeError:
            return
        if sock.fileno() >= 0:
            _warn(f"unclosed transport {self!r}", ResourceWarning, source=self)
            sock.close()

    @_utils.inherit_doc(base_selector.SelectorStreamTransport)
    def is_closed(self) -> bool:
        return self.__socket.fileno() < 0

    @_utils.inherit_doc(base_selector.SelectorStreamTransport)
    def close(self) -> None:
        try:
            if self.__standard_compatible and self.__socket.fileno() >= 0:
                self._retry(lambda: self._try_ssl_method(self.__socket.unwrap), self.__ssl_shutdown_timeout)
        except (OSError, ValueError):
            pass
        finally:
            _close_stream_socket(self.__socket)

    @_utils.inherit_doc(base_selector.SelectorStreamTransport)
    def recv_noblock(self, bufsize: int) -> bytes:
        try:
            return self._try_ssl_method(self.__socket.recv, bufsize)
        except _ssl_module.SSLZeroReturnError if _ssl_module else ():
            return b""

    @_utils.inherit_doc(base_selector.SelectorStreamTransport)
    def recv_noblock_into(self, buffer: WriteableBuffer) -> int:
        try:
            return self._try_ssl_method(self.__socket.recv_into, buffer)
        except _ssl_module.SSLZeroReturnError if _ssl_module else ():
            return 0

    @_utils.inherit_doc(base_selector.SelectorStreamTransport)
    def send_noblock(self, data: bytes | bytearray | memoryview) -> int:
        try:
            return self._try_ssl_method(self.__socket.send, data)
        except _ssl_module.SSLZeroReturnError if _ssl_module else () as exc:
            raise _utils.error_from_errno(errno.ECONNRESET) from exc

    @_utils.inherit_doc(base_selector.SelectorStreamTransport)
    def send_all_from_iterable(self, iterable_of_data: Iterable[bytes | bytearray | memoryview], timeout: float) -> None:
        # Send a whole chunk to minimize TLS exchanges
        data = b"".join(iterable_of_data)
        del iterable_of_data
        return self.send_all(data, timeout)

    @_utils.inherit_doc(base_selector.SelectorStreamTransport)
    def send_eof(self) -> None:
        # ssl.SSLSocket.shutdown() would close both read and write streams
        raise UnsupportedOperation("SSL/TLS API does not support sending EOF.")

    def _try_ssl_method(self, socket_method: Callable[_P, _T_Return], /, *args: _P.args, **kwargs: _P.kwargs) -> _T_Return:
        if _ssl_module is None:
            raise RuntimeError("stdlib ssl module not available")
        try:
            return socket_method(*args, **kwargs)
        except (_ssl_module.SSLWantReadError, _ssl_module.SSLSyscallError):
            raise base_selector.WouldBlockOnRead(self.__socket.fileno()) from None
        except _ssl_module.SSLWantWriteError:
            raise base_selector.WouldBlockOnWrite(self.__socket.fileno()) from None

    @property
    @_utils.inherit_doc(base_selector.SelectorStreamTransport)
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__extra_attributes


class SocketDatagramTransport(base_selector.SelectorDatagramTransport):
    """
    A datagram transport implementation which wraps a datagram :class:`~socket.socket`.
    """

    __slots__ = ("__socket", "__max_datagram_size", "__extra_attributes")

    def __init__(
        self,
        sock: socket.socket,
        retry_interval: float,
        *,
        max_datagram_size: int = constants.MAX_DATAGRAM_BUFSIZE,
        selector_factory: Callable[[], selectors.BaseSelector] | None = None,
    ) -> None:
        """
        Parameters:
            sock: The :data:`~socket.SOCK_DGRAM` socket to wrap.
            retry_interval: The maximum wait time to wait for a blocking operation before retrying.
                            Set it to :data:`math.inf` to disable this feature.
            max_datagram_size: The maximum packet size supported by :manpage:`recvfrom(2)` for the current socket.
            selector_factory: If given, the callable object to use to create a new :class:`selectors.BaseSelector` instance.
        """
        super().__init__(retry_interval=retry_interval, selector_factory=selector_factory)

        if max_datagram_size <= 0:
            raise ValueError("max_datagram_size must not be <= 0")

        self.__max_datagram_size: int = max_datagram_size

        _utils.check_socket_no_ssl(sock)
        if sock.type != socket.SOCK_DGRAM:
            raise ValueError("A 'SOCK_DGRAM' socket is expected")

        self.__socket: socket.socket = sock
        self.__socket.setblocking(False)

        self.__extra_attributes = MappingProxyType(socket_tools._get_socket_extra(self.__socket))

    def __del__(self, *, _warn: _utils.WarnCallback = warnings.warn) -> None:
        try:
            sock: socket.socket = self.__socket
        except AttributeError:
            return
        if sock.fileno() >= 0:
            _warn(f"unclosed transport {self!r}", ResourceWarning, source=self)
            sock.close()

    @_utils.inherit_doc(base_selector.SelectorDatagramTransport)
    def is_closed(self) -> bool:
        return self.__socket.fileno() < 0

    @_utils.inherit_doc(base_selector.SelectorDatagramTransport)
    def close(self) -> None:
        self.__socket.close()

    @_utils.inherit_doc(base_selector.SelectorDatagramTransport)
    def recv_noblock(self) -> bytes:
        max_datagram_size: int = self.__max_datagram_size
        try:
            return self.__socket.recv(max_datagram_size)
        except (BlockingIOError, InterruptedError):
            raise base_selector.WouldBlockOnRead(self.__socket.fileno()) from None

    @_utils.inherit_doc(base_selector.SelectorDatagramTransport)
    def send_noblock(self, data: bytes | bytearray | memoryview) -> None:
        try:
            self.__socket.send(data)
        except (BlockingIOError, InterruptedError):
            raise base_selector.WouldBlockOnWrite(self.__socket.fileno()) from None

    @property
    @_utils.inherit_doc(base_selector.SelectorDatagramTransport)
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__extra_attributes
