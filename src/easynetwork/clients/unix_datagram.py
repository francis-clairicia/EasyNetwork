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
"""Unix datagram client implementation module.

.. versionadded:: 1.1
"""

from __future__ import annotations

__all__ = ["UnixDatagramClient"]

import contextlib
import os
import socket as _socket
import threading
import warnings
from collections.abc import Iterator
from typing import Any, final, overload

from .._typevars import _T_ReceivedPacket, _T_SentPacket
from ..exceptions import ClientClosedError
from ..lowlevel import _lock, _unix_utils, _utils, constants
from ..lowlevel.api_sync.endpoints.datagram import DatagramEndpoint
from ..lowlevel.api_sync.transports import socket as _transport_socket
from ..lowlevel.socket import SocketProxy, UnixSocketAddress, UNIXSocketAttribute
from ..protocol import DatagramProtocol
from .abc import AbstractNetworkClient


class UnixDatagramClient(AbstractNetworkClient[_T_SentPacket, _T_ReceivedPacket]):
    """
    A Unix datagram client.

    .. versionadded:: 1.1
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
        path: str | os.PathLike[str] | bytes | UnixSocketAddress,
        /,
        protocol: DatagramProtocol[_T_SentPacket, _T_ReceivedPacket],
        *,
        local_path: str | os.PathLike[str] | bytes | UnixSocketAddress | None = ...,
        retry_interval: float = ...,
    ) -> None: ...

    @overload
    def __init__(
        self,
        socket: _socket.socket,
        /,
        protocol: DatagramProtocol[_T_SentPacket, _T_ReceivedPacket],
        *,
        retry_interval: float = ...,
    ) -> None: ...

    def __init__(
        self,
        __arg: _socket.socket | str | os.PathLike[str] | bytes | UnixSocketAddress,
        /,
        protocol: DatagramProtocol[_T_SentPacket, _T_ReceivedPacket],
        *,
        retry_interval: float = 1.0,
        **kwargs: Any,
    ) -> None:
        """
        Common Parameters:
            protocol: The :term:`protocol object` to use.

        Connection Parameters:
            path: Path of the socket.
            local_path: If given, is a Unix socket address used to bind the socket locally.

        Socket Parameters:
            socket: An already connected Unix datagram :class:`socket.socket`. If `socket` is given,
            `local_path` should not be specified.

        Keyword Arguments:
            retry_interval: The maximum wait time to wait for a blocking operation before retrying.
                            Set it to :data:`math.inf` to disable this feature.
        """
        super().__init__()

        socket: _socket.socket
        match __arg:
            case _socket.socket() if kwargs:
                raise TypeError("Invalid arguments")
            case _socket.socket() as socket:
                pass
            case path:
                path = _unix_utils.convert_unix_socket_address(path)
                kwargs["local_path"] = _unix_utils.convert_optional_unix_socket_address(kwargs.get("local_path"))
                if not kwargs["local_path"]:
                    if _unix_utils.platform_supports_automatic_socket_bind():
                        # Explictly set local_path to empty string.
                        # local_path could be None at this point.
                        kwargs["local_path"] = ""
                    else:
                        msg = "local_path parameter is required on this platform and cannot be an empty string."
                        note = "Automatic socket bind is not supported."
                        raise _utils.exception_with_notes(ValueError(msg), note)
                socket = _create_unix_datagram_socket(path, **kwargs)

        try:
            _unix_utils.check_unix_socket_family(socket.family)
            _utils.check_socket_is_connected(socket)

            local_name = UnixSocketAddress.from_raw(socket.getsockname())
            if local_name.is_unnamed():
                raise ValueError(f"{self.__class__.__name__} requires the socket to be named.")

            transport = _transport_socket.SocketDatagramTransport(
                socket,
                retry_interval=retry_interval,
                max_datagram_size=constants.MAX_DATAGRAM_BUFSIZE,
            )
        except BaseException:
            socket.close()
            raise

        self.__send_lock = _lock.ForkSafeLock(threading.Lock)
        self.__receive_lock = _lock.ForkSafeLock(threading.Lock)
        try:
            self.__endpoint: DatagramEndpoint[_T_SentPacket, _T_ReceivedPacket] = DatagramEndpoint(transport, protocol)
            self.__socket_proxy = SocketProxy(transport.extra(UNIXSocketAttribute.socket), lock=self.__send_lock.get)
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

        Important:
            The lock acquisition time is included in the `timeout`.

            This means that you may get a :exc:`TimeoutError` because it took too long to get the lock.

        Parameters:
            packet: the Python object to send.
            timeout: the allowed time (in seconds) for blocking operations.

        Raises:
            ClientClosedError: the client object is closed.
            TimeoutError: the send operation does not end up after `timeout` seconds.
            OSError: unrelated OS error occurred. You should check :attr:`OSError.errno`.
        """
        with _utils.lock_with_timeout(self.__send_lock.get(), timeout) as timeout:
            endpoint = self.__endpoint
            if endpoint.is_closed():
                raise self.__closed()
            with self.__convert_socket_error(endpoint=endpoint):
                endpoint.send_packet(packet, timeout=timeout)
                _utils.check_real_socket_state(endpoint.extra(UNIXSocketAttribute.socket))

    def recv_packet(self, *, timeout: float | None = None) -> _T_ReceivedPacket:
        """
        Waits for a new packet from the remote endpoint. Thread-safe.

        If `timeout` is not :data:`None`, the entire receive operation will take at most `timeout` seconds.

        Important:
            The lock acquisition time is included in the `timeout`.

            This means that you may get a :exc:`TimeoutError` because it took too long to get the lock.

        Parameters:
            timeout: the allowed time (in seconds) for blocking operations.

        Raises:
            ClientClosedError: the client object is closed.
            TimeoutError: the receive operation does not end up after `timeout` seconds.
            OSError: unrelated OS error occurred. You should check :attr:`OSError.errno`.
            DatagramProtocolParseError: invalid data received.

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
    def __convert_socket_error(cls, *, endpoint: DatagramEndpoint[Any, Any] | None) -> Iterator[None]:
        try:
            yield
        except OSError as exc:
            if exc.errno in constants.CLOSED_SOCKET_ERRNOS:
                if endpoint is not None and endpoint.is_closed():
                    # close() called while recv_packet() is awaiting...
                    raise cls.__closed() from exc
                exc.add_note("The socket file descriptor was closed unexpectedly.")
            raise

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


def _create_unix_datagram_socket(
    path: str | bytes,
    *,
    local_path: str | bytes | None = None,
) -> _socket.socket:
    family: int = getattr(_socket, "AF_UNIX")
    socket = _socket.socket(family, _socket.SOCK_DGRAM, 0)
    try:
        if local_path is not None:
            try:
                socket.bind(local_path)
            except OSError as exc:
                raise _utils.convert_socket_bind_error(exc, local_path) from None
        socket.connect(path)
    except BaseException:
        socket.close()
        raise
    return socket
