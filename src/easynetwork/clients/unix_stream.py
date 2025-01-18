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
"""Unix stream client implementation module.

.. versionadded:: 1.1
"""

from __future__ import annotations

__all__ = ["UnixStreamClient"]

import contextlib
import errno as _errno
import os
import socket as _socket
import threading
import warnings
from collections.abc import Iterator
from typing import Any, final, overload

from .._typevars import _T_ReceivedPacket, _T_SentPacket
from ..exceptions import ClientClosedError
from ..lowlevel import _lock, _unix_utils, _utils, constants
from ..lowlevel.api_sync.endpoints.stream import StreamEndpoint
from ..lowlevel.api_sync.transports import socket as _transport_socket
from ..lowlevel.socket import SocketProxy, UnixCredentials, UnixSocketAddress, UNIXSocketAttribute
from ..protocol import AnyStreamProtocolType
from .abc import AbstractNetworkClient


class UnixStreamClient(AbstractNetworkClient[_T_SentPacket, _T_ReceivedPacket]):
    """
    A Unix stream client.

    .. versionadded:: 1.1
    """

    __slots__ = (
        "__endpoint",
        "__socket_proxy",
        "__send_lock",
        "__receive_lock",
        "__peer_creds_cache",
    )

    @overload
    def __init__(
        self,
        path: str | os.PathLike[str] | bytes | UnixSocketAddress,
        /,
        protocol: AnyStreamProtocolType[_T_SentPacket, _T_ReceivedPacket],
        *,
        connect_timeout: float | None = ...,
        local_path: str | os.PathLike[str] | bytes | UnixSocketAddress | None = ...,
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
        max_recv_size: int | None = ...,
        retry_interval: float = ...,
    ) -> None: ...

    def __init__(
        self,
        __arg: _socket.socket | str | os.PathLike[str] | bytes | UnixSocketAddress,
        /,
        protocol: AnyStreamProtocolType[_T_SentPacket, _T_ReceivedPacket],
        *,
        max_recv_size: int | None = None,
        retry_interval: float = 1.0,
        **kwargs: Any,
    ) -> None:
        """
        Common Parameters:
            protocol: The :term:`protocol object` to use.

        Connection Parameters:
            path: Path of the socket.
            connect_timeout: The connection timeout (in seconds).
            local_path: If given, is a Unix socket address used to bind the socket locally.
                        If `local_path` points to a filepath, it will *not* be deleted on client close.

        Socket Parameters:
            socket: An already connected Unix :class:`socket.socket`. If `socket` is given,
                    none of `connect_timeout` and `local_path` should be specified.

        Keyword Arguments:
            max_recv_size: Read buffer size. If not given, a default reasonable value is used.
            retry_interval: The maximum wait time to wait for a blocking operation before retrying.
                            Set it to :data:`math.inf` to disable this feature.
        """
        super().__init__()

        from ..lowlevel._stream import _check_any_protocol

        _check_any_protocol(protocol)

        if max_recv_size is None:
            max_recv_size = constants.DEFAULT_STREAM_BUFSIZE

        socket: _socket.socket
        match __arg:
            case _socket.socket() if kwargs:
                raise TypeError("Invalid arguments")
            case _socket.socket() as socket:
                pass
            case path:
                path = _unix_utils.convert_unix_socket_address(path)
                kwargs["local_path"] = _unix_utils.convert_optional_unix_socket_address(kwargs.get("local_path"))
                socket = _create_unix_stream_connection(path, **kwargs)

        try:
            _unix_utils.check_unix_socket_family(socket.family)
            _utils.check_socket_is_connected(socket)

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
            trsocket = transport.extra(UNIXSocketAttribute.socket)
            self.__peer_creds_cache = _unix_utils.UnixCredsContainer(trsocket)
            self.__socket_proxy = SocketProxy(trsocket, lock=self.__send_lock.get)
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
            A timeout on a send operation is unusual.

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
                _utils.check_real_socket_state(endpoint.extra(UNIXSocketAttribute.socket))

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

    def get_local_name(self) -> UnixSocketAddress:
        """
        Returns the socket name. Thread-safe.

        Raises:
            ClientClosedError: the client object is closed.
            OSError: unrelated OS error occurred. You should check :attr:`OSError.errno`.

        Returns:
            the client's local name.
        """
        with self.__send_lock.get():
            endpoint = self.__endpoint
            if endpoint.is_closed():
                raise self.__closed()
            sock_name = endpoint.extra(UNIXSocketAttribute.sockname)
            return UnixSocketAddress.from_raw(sock_name)

    def get_peer_name(self) -> UnixSocketAddress:
        """
        Returns the peer socket name. Thread-safe.

        Raises:
            ClientClosedError: the client object is closed.
            OSError: unrelated OS error occurred. You should check :attr:`OSError.errno`.

        Returns:
            the client's peer name.
        """
        with self.__send_lock.get():
            endpoint = self.__endpoint
            if endpoint.is_closed():
                raise self.__closed()
            peer_name = endpoint.extra(UNIXSocketAttribute.peername)
            return UnixSocketAddress.from_raw(peer_name)

    def get_peer_credentials(self) -> UnixCredentials:
        """
        Returns the credentials of the peer process connected to this socket. Thread-safe.

        Raises:
            ClientClosedError: the client object is closed.
            NotImplementedError: The current platform is not supported.
            OSError: unrelated OS error occurred. You should check :attr:`OSError.errno`.
        """
        with self.__send_lock.get():
            endpoint = self.__endpoint
            if endpoint.is_closed():
                raise self.__closed()
            return self.__peer_creds_cache.get()

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


def _create_unix_stream_connection(
    path: str | bytes,
    *,
    connect_timeout: float | None = None,
    local_path: str | bytes | None = None,
) -> _socket.socket:
    family: int = getattr(_socket, "AF_UNIX")
    socket = _socket.socket(family, _socket.SOCK_STREAM, 0)
    try:
        if local_path is not None:
            try:
                socket.bind(local_path)
            except OSError as exc:
                raise _utils.convert_socket_bind_error(exc, local_path) from None
        socket.settimeout(connect_timeout)
        socket.connect(path)
    except BaseException:
        socket.close()
        raise
    return socket
