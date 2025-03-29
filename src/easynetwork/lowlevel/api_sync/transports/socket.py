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
    "SSLStreamListener",
    "SSLStreamTransport",
    "SocketDatagramListener",
    "SocketDatagramTransport",
    "SocketStreamListener",
    "SocketStreamTransport",
]

import concurrent.futures
import errno
import functools
import itertools
import logging
import selectors
import socket
import sys
import threading
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
from ... import _lock, _unix_utils, _utils, constants, socket as socket_tools
from . import base_selector

if TYPE_CHECKING:
    from socket import _Address, _RetAddress
    from ssl import SSLContext, SSLSession, SSLSocket

    from _typeshed import ReadableBuffer, WriteableBuffer

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

    if sys.platform != "win32" and hasattr(socket.socket, "recvmsg"):

        @_utils.inherit_doc(base_selector.SelectorStreamTransport)
        def recv_noblock_with_ancillary(self, bufsize: int, ancillary_bufsize: int) -> tuple[bytes, list[tuple[int, int, bytes]]]:
            if not _unix_utils.is_unix_socket_family(self.__socket.family):
                return super().recv_noblock_with_ancillary(bufsize, ancillary_bufsize)
            try:
                msg, ancdata, _, _ = self.__socket.recvmsg(bufsize, ancillary_bufsize)
            except (BlockingIOError, InterruptedError):
                raise base_selector.WouldBlockOnRead(self.__socket.fileno()) from None
            else:
                return msg, ancdata

    if sys.platform != "win32" and hasattr(socket.socket, "recvmsg_into"):

        @_utils.inherit_doc(base_selector.SelectorStreamTransport)
        def recv_noblock_with_ancillary_into(
            self,
            buffer: WriteableBuffer,
            ancillary_bufsize: int,
        ) -> tuple[int, list[tuple[int, int, bytes]]]:
            if not _unix_utils.is_unix_socket_family(self.__socket.family):
                return super().recv_noblock_with_ancillary_into(buffer, ancillary_bufsize)
            try:
                nbytes, ancdata, _, _ = self.__socket.recvmsg_into([buffer], ancillary_bufsize)
            except (BlockingIOError, InterruptedError):
                raise base_selector.WouldBlockOnRead(self.__socket.fileno()) from None
            else:
                return nbytes, ancdata

    @_utils.inherit_doc(base_selector.SelectorStreamTransport)
    def send_noblock(self, data: bytes | bytearray | memoryview) -> int:
        try:
            return self.__socket.send(data)
        except (BlockingIOError, InterruptedError):
            raise base_selector.WouldBlockOnWrite(self.__socket.fileno()) from None

    if sys.platform != "win32" and hasattr(socket.socket, "sendmsg"):

        if constants.SC_IOV_MAX > 0:  # pragma: no branch

            @_utils.inherit_doc(base_selector.SelectorStreamTransport)
            def send_all_noblock_with_ancillary(
                self,
                iterable_of_data: Iterable[bytes | bytearray | memoryview],
                ancillary_data: Iterable[tuple[int, int, ReadableBuffer]],
            ) -> None:
                if not _unix_utils.is_unix_socket_family(self.__socket.family):
                    return super().send_all_noblock_with_ancillary(iterable_of_data, ancillary_data)
                buffers: deque[memoryview] = deque(map(memoryview, iterable_of_data))  # type: ignore[arg-type]
                del iterable_of_data
                try:
                    sent = self.__socket.sendmsg(itertools.islice(buffers, constants.SC_IOV_MAX), ancillary_data)
                except (BlockingIOError, InterruptedError):
                    raise base_selector.WouldBlockOnWrite(self.__socket.fileno()) from None
                _utils.adjust_leftover_buffer(buffers, sent)
                if buffers:
                    raise _utils.error_from_errno(errno.EMSGSIZE)

            @_utils.inherit_doc(base_selector.SelectorStreamTransport)
            def send_all_with_ancillary(
                self,
                iterable_of_data: Iterable[bytes | bytearray | memoryview],
                ancillary_data: Iterable[tuple[int, int, ReadableBuffer]],
                timeout: float,
            ) -> None:
                if hasattr(ancillary_data, "__next__"):
                    # Do not send the iterator directly because if sendmsg() blocks,
                    # it would retry with an already consumed iterator.
                    ancillary_data = list(ancillary_data)
                return super().send_all_with_ancillary(iterable_of_data, ancillary_data, timeout)

            @_utils.inherit_doc(base_selector.SelectorStreamTransport)
            def send_all_from_iterable(self, iterable_of_data: Iterable[bytes | bytearray | memoryview], timeout: float) -> None:
                buffers: deque[memoryview] = deque(map(memoryview, iterable_of_data))  # type: ignore[arg-type]
                del iterable_of_data

                socket_sendmsg = self.__socket.sendmsg

                def try_sendmsg() -> int:
                    try:
                        return socket_sendmsg(itertools.islice(buffers, constants.SC_IOV_MAX))
                    except (BlockingIOError, InterruptedError):
                        raise base_selector.WouldBlockOnWrite(self.__socket.fileno()) from None

                while True:
                    sent, timeout = self._retry(try_sendmsg, timeout)
                    _utils.adjust_leftover_buffer(buffers, sent)
                    if not buffers:
                        break

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
    def abort(self) -> None:
        _close_stream_socket(self.__socket)

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

    if sys.platform != "win32" and hasattr(socket.socket, "recvmsg"):

        @_utils.inherit_doc(base_selector.SelectorDatagramTransport)
        def recv_noblock_with_ancillary(self, ancillary_bufsize: int) -> tuple[bytes, list[tuple[int, int, bytes]]]:
            if not _unix_utils.is_unix_socket_family(self.__socket.family):
                return super().recv_noblock_with_ancillary(ancillary_bufsize)
            max_datagram_size: int = self.__max_datagram_size
            try:
                msg, ancdata, _, _ = self.__socket.recvmsg(max_datagram_size, ancillary_bufsize)
            except (BlockingIOError, InterruptedError):
                raise base_selector.WouldBlockOnRead(self.__socket.fileno()) from None
            else:
                return msg, ancdata

    @_utils.inherit_doc(base_selector.SelectorDatagramTransport)
    def send_noblock(self, data: bytes | bytearray | memoryview) -> None:
        try:
            self.__socket.send(data)
        except (BlockingIOError, InterruptedError):
            raise base_selector.WouldBlockOnWrite(self.__socket.fileno()) from None

    if sys.platform != "win32" and hasattr(socket.socket, "sendmsg"):

        @_utils.inherit_doc(base_selector.SelectorDatagramTransport)
        def send_noblock_with_ancillary(
            self,
            data: bytes | bytearray | memoryview,
            ancillary_data: Iterable[tuple[int, int, ReadableBuffer]],
        ) -> None:
            if not _unix_utils.is_unix_socket_family(self.__socket.family):
                return super().send_noblock_with_ancillary(data, ancillary_data)
            try:
                self.__socket.sendmsg([data], ancillary_data)
            except (BlockingIOError, InterruptedError):
                raise base_selector.WouldBlockOnWrite(self.__socket.fileno()) from None

        @_utils.inherit_doc(base_selector.SelectorDatagramTransport)
        def send_with_ancillary(
            self,
            data: bytes | bytearray | memoryview,
            ancillary_data: Iterable[tuple[int, int, ReadableBuffer]],
            timeout: float,
        ) -> None:
            if hasattr(ancillary_data, "__next__"):
                # Do not send the iterator directly because if sendmsg() blocks,
                # it would retry with an already consumed iterator.
                ancillary_data = list(ancillary_data)
            return super().send_with_ancillary(data, ancillary_data, timeout)

    @property
    @_utils.inherit_doc(base_selector.SelectorDatagramTransport)
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__extra_attributes


class SocketStreamListener(base_selector.SelectorListener[SocketStreamTransport]):
    """
    A stream data transport listener implementation which wraps a listener :class:`~socket.socket`.

    .. versionadded:: NEXT_VERSION
    """

    __slots__ = ("__socket", "__extra_attributes")

    def __init__(
        self,
        sock: socket.socket,
        *,
        selector_factory: Callable[[], selectors.BaseSelector] | None = None,
    ) -> None:
        """
        Parameters:
            sock: The :data:`~socket.SOCK_STREAM` listener socket to wrap.
            selector_factory: If given, the callable object to use to create a new :class:`selectors.BaseSelector` instance.
        """
        super().__init__(retry_interval=1.0, selector_factory=selector_factory)

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
            _warn(f"unclosed listener {self!r}", ResourceWarning, source=self)
            sock.close()

    @_utils.inherit_doc(base_selector.SelectorListener)
    def is_closed(self) -> bool:
        return self.__socket.fileno() < 0

    @_utils.inherit_doc(base_selector.SelectorListener)
    def close(self) -> None:
        self.__socket.close()

    @_utils.inherit_doc(base_selector.SelectorListener)
    def accept_noblock(
        self,
        handler: Callable[[SocketStreamTransport], _T_Return],
        executor: concurrent.futures.Executor,
    ) -> concurrent.futures.Future[_T_Return]:
        try:
            client_sock, _ = self.__socket.accept()
        except (BlockingIOError, InterruptedError):
            raise base_selector.WouldBlockOnRead(self.__socket.fileno()) from None

        future = executor.submit(self.__in_executor, client_sock, handler)
        future.add_done_callback(functools.partial(self.__on_task_done, client_sock=client_sock))
        return future

    def is_accept_capacity_error(self, exc: Exception) -> bool:
        match exc:
            case OSError(errno=exc_errno) if exc_errno in constants.ACCEPT_CAPACITY_ERRNOS:
                return True
            case _:
                return False

    def accept_capacity_error_sleep_time(self) -> float:
        return constants.ACCEPT_CAPACITY_ERROR_SLEEP_TIME

    def __in_executor(self, client_sock: socket.socket, handler: Callable[[SocketStreamTransport], _T_Return]) -> _T_Return:
        try:
            transport = SocketStreamTransport(client_sock, retry_interval=1.0, selector_factory=self._selector_factory)
        except BaseException:
            client_sock.close()
            raise
        else:
            del client_sock
            return handler(transport)
        finally:
            del self, handler  # Break reference cycle with raised exception.

    @staticmethod
    def __on_task_done(future: concurrent.futures.Future[Any], /, *, client_sock: socket.socket) -> None:
        if future.cancelled():
            client_sock.close()

    @property
    @_utils.inherit_doc(base_selector.SelectorListener)
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__extra_attributes


class SSLStreamListener(base_selector.SelectorListener[SSLStreamTransport]):
    """
    A stream data transport listener implementation which wraps a listener :class:`~socket.socket`.

    .. versionadded:: NEXT_VERSION
    """

    __slots__ = (
        "__socket",
        "__ssl_context",
        "__standard_compatible",
        "__handshake_timeout",
        "__shutdown_timeout",
        "__handshake_error_handler",
        "__extra_attributes",
    )

    def __init__(
        self,
        sock: socket.socket,
        ssl_context: SSLContext,
        *,
        handshake_timeout: float | None = None,
        shutdown_timeout: float | None = None,
        standard_compatible: bool = True,
        handshake_error_handler: Callable[[Exception], None] | None = None,
        selector_factory: Callable[[], selectors.BaseSelector] | None = None,
    ) -> None:
        """
        Parameters:
            sock: The :data:`~socket.SOCK_STREAM` listener socket to wrap.
            ssl_context: a :class:`ssl.SSLContext` object to use to create the client transport.
            handshake_timeout: The time in seconds to wait for the TLS handshake to complete before aborting the connection.
                               ``60.0`` seconds if :data:`None` (default).
            shutdown_timeout: The time in seconds to wait for the SSL shutdown to complete before aborting the connection.
                              ``30.0`` seconds if :data:`None` (default).
            standard_compatible: If :data:`False`, skip the closing handshake when closing the connection,
                                 and don't raise an exception if the peer does the same.
            selector_factory: If given, the callable object to use to create a new :class:`selectors.BaseSelector` instance.
        """
        super().__init__(retry_interval=1.0, selector_factory=selector_factory)

        _utils.check_socket_no_ssl(sock)
        if sock.type != socket.SOCK_STREAM:
            raise ValueError("A 'SOCK_STREAM' socket is expected")
        self.__socket: socket.socket = sock
        self.__socket.setblocking(False)

        self.__ssl_context: SSLContext = ssl_context
        self.__handshake_timeout: float | None = handshake_timeout
        self.__shutdown_timeout: float | None = shutdown_timeout
        self.__standard_compatible: bool = standard_compatible
        self.__handshake_error_handler: Callable[[Exception], None] | None = handshake_error_handler

        self.__extra_attributes = MappingProxyType(
            {
                **socket_tools._get_socket_extra(self.__socket),
                **self.__make_tls_extra_attributes(self.__ssl_context, self.__standard_compatible),
            }
        )

    def __del__(self, *, _warn: _utils.WarnCallback = warnings.warn) -> None:
        try:
            sock: socket.socket = self.__socket
        except AttributeError:
            return
        if sock.fileno() >= 0:
            _warn(f"unclosed listener {self!r}", ResourceWarning, source=self)
            sock.close()

    @_utils.inherit_doc(base_selector.SelectorListener)
    def is_closed(self) -> bool:
        return self.__socket.fileno() < 0

    @_utils.inherit_doc(base_selector.SelectorListener)
    def close(self) -> None:
        self.__socket.close()

    @_utils.inherit_doc(base_selector.SelectorListener)
    def accept_noblock(
        self,
        handler: Callable[[SSLStreamTransport], _T_Return],
        executor: concurrent.futures.Executor,
    ) -> concurrent.futures.Future[_T_Return]:
        try:
            client_sock, _ = self.__socket.accept()
        except (BlockingIOError, InterruptedError):
            raise base_selector.WouldBlockOnRead(self.__socket.fileno()) from None

        client_task_future: concurrent.futures.Future[_T_Return] = concurrent.futures.Future()

        whole_task_future = executor.submit(self.__in_executor, client_sock, handler, client_task_future)
        whole_task_future.add_done_callback(
            functools.partial(self.__on_executor_task_done, client_sock=client_sock, client_task_future=client_task_future)
        )
        client_task_future.add_done_callback(functools.partial(self.__on_client_task_done, whole_task_future=whole_task_future))

        return client_task_future

    def is_accept_capacity_error(self, exc: Exception) -> bool:
        match exc:
            case OSError(errno=exc_errno) if exc_errno in constants.ACCEPT_CAPACITY_ERRNOS:
                return True
            case _:
                return False

    def accept_capacity_error_sleep_time(self) -> float:
        return constants.ACCEPT_CAPACITY_ERROR_SLEEP_TIME

    def __in_executor(
        self,
        client_sock: socket.socket,
        handler: Callable[[SSLStreamTransport], _T_Return],
        client_task_future: concurrent.futures.Future[_T_Return],
    ) -> None:
        try:
            transport = SSLStreamTransport(
                client_sock,
                self.__ssl_context,
                retry_interval=1.0,
                selector_factory=self._selector_factory,
                server_side=True,
                handshake_timeout=self.__handshake_timeout,
                shutdown_timeout=self.__shutdown_timeout,
                standard_compatible=self.__standard_compatible,
            )
        except Exception as exc:
            try:
                if client_task_future.cancel():  # pragma: no branch
                    client_task_future.set_running_or_notify_cancel()
            finally:
                client_sock.close()

            handshake_error_handler = self.__handshake_error_handler
            if handshake_error_handler is None:
                self.__default_handshake_error_handler(exc)
            else:
                try:
                    handshake_error_handler(exc)
                except Exception as error_handler_exc:
                    self.__default_handshake_error_handler(error_handler_exc)
        except BaseException as exc:
            try:
                if client_task_future.set_running_or_notify_cancel():
                    client_task_future.set_exception(exc)
                else:
                    self.__default_handshake_error_handler(exc)
            finally:
                client_sock.close()
        else:
            del client_sock
            if client_task_future.set_running_or_notify_cancel():
                try:
                    result = handler(transport)
                except BaseException as exc:
                    client_task_future.set_exception(exc)
                else:
                    client_task_future.set_result(result)
            else:
                transport.abort()
            del transport
        finally:
            del self, handler, client_task_future  # Break reference cycle with raised exception.

    @staticmethod
    def __default_handshake_error_handler(exc: BaseException) -> None:
        logger = logging.getLogger(__name__)
        logger.warning("Error in client task (during TLS handshake)", exc_info=exc)

    @staticmethod
    def __on_executor_task_done(
        whole_task_future: concurrent.futures.Future[Any],
        /,
        *,
        client_sock: socket.socket,
        client_task_future: concurrent.futures.Future[Any],
    ) -> None:
        if whole_task_future.cancelled():
            try:
                if client_task_future.cancel():  # pragma: no branch
                    client_task_future.set_running_or_notify_cancel()
            finally:
                client_sock.close()

    @staticmethod
    def __on_client_task_done(
        client_task_future: concurrent.futures.Future[Any],
        /,
        *,
        whole_task_future: concurrent.futures.Future[Any],
    ) -> None:
        if client_task_future.cancelled():
            whole_task_future.cancel()

    @staticmethod
    def __make_tls_extra_attributes(ssl_context: SSLContext, standard_compatible: bool) -> dict[Any, Callable[[], Any]]:
        return {
            socket_tools.TLSAttribute.sslcontext: lambda: ssl_context,
            socket_tools.TLSAttribute.standard_compatible: lambda: standard_compatible,
        }

    @property
    @_utils.inherit_doc(base_selector.SelectorListener)
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__extra_attributes


class SocketDatagramListener(base_selector.SelectorDatagramListener["_RetAddress"]):
    """
    A datagram listener implementation which wraps a datagram :class:`~socket.socket`.

    .. versionadded:: NEXT_VERSION
    """

    __slots__ = ("__socket", "__extra_attributes", "__send_lock")

    def __init__(
        self,
        sock: socket.socket,
        *,
        selector_factory: Callable[[], selectors.BaseSelector] | None = None,
    ) -> None:
        """
        Parameters:
            sock: The :data:`~socket.SOCK_DGRAM` listener socket to wrap.
            selector_factory: If given, the callable object to use to create a new :class:`selectors.BaseSelector` instance.
        """
        super().__init__(retry_interval=1.0, selector_factory=selector_factory)

        _utils.check_socket_no_ssl(sock)
        if sock.type != socket.SOCK_DGRAM:
            raise ValueError("A 'SOCK_DGRAM' socket is expected")
        self.__socket: socket.socket = sock
        self.__socket.setblocking(False)

        self.__send_lock = _lock.ForkSafeLock(threading.Lock)

        socket_proxy = socket_tools.SocketProxy(self.__socket, lock=self.__send_lock.get)
        self.__extra_attributes = MappingProxyType(socket_tools._get_socket_extra(socket_proxy, wrap_in_proxy=False))

    def __del__(self, *, _warn: _utils.WarnCallback = warnings.warn) -> None:
        try:
            sock: socket.socket = self.__socket
        except AttributeError:
            return
        if sock.fileno() >= 0:
            _warn(f"unclosed listener {self!r}", ResourceWarning, source=self)
            sock.close()

    @_utils.inherit_doc(base_selector.SelectorListener)
    def is_closed(self) -> bool:
        with self.__send_lock.get():
            return self.__socket.fileno() < 0

    @_utils.inherit_doc(base_selector.SelectorListener)
    def close(self) -> None:
        with self.__send_lock.get():
            self.__socket.close()

    @_utils.inherit_doc(base_selector.SelectorListener)
    def recv_from_noblock(
        self,
        handler: Callable[[bytes, _RetAddress], _T_Return],
        executor: concurrent.futures.Executor,
    ) -> concurrent.futures.Future[_T_Return]:
        try:
            datagram, client_address = self.__socket.recvfrom(constants.MAX_DATAGRAM_BUFSIZE)
        except (BlockingIOError, InterruptedError):
            raise base_selector.WouldBlockOnRead(self.__socket.fileno()) from None
        else:
            return executor.submit(handler, datagram, client_address)

    @_utils.inherit_doc(base_selector.SelectorDatagramListener)
    def send_to_noblock(self, data: bytes | bytearray | memoryview, address: _Address) -> None:
        with self.__send_lock.get():
            return self.__send_to_noblock_unsafe_impl(data, address)

    @_utils.inherit_doc(base_selector.SelectorDatagramListener)
    def send_to(self, data: bytes | bytearray | memoryview, address: _Address, timeout: float) -> None:
        with _utils.lock_with_timeout(self.__send_lock.get(), timeout) as timeout:
            self._retry(lambda: self.__send_to_noblock_unsafe_impl(data, address), timeout)

    def __send_to_noblock_unsafe_impl(self, data: bytes | bytearray | memoryview, address: _Address) -> None:
        try:
            self.__socket.sendto(data, address)
        except (BlockingIOError, InterruptedError):
            raise base_selector.WouldBlockOnWrite(self.__socket.fileno()) from None

    @property
    @_utils.inherit_doc(base_selector.SelectorDatagramListener)
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__extra_attributes
