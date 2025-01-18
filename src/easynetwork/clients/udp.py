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
"""UDP Network client implementation module."""

from __future__ import annotations

__all__ = ["UDPNetworkClient"]

import contextlib
import socket as _socket
import threading
import warnings
from collections.abc import Iterator
from typing import Any, final, overload

from .._typevars import _T_ReceivedPacket, _T_SentPacket
from ..exceptions import ClientClosedError
from ..lowlevel import _lock, _utils, constants
from ..lowlevel.api_sync.endpoints.datagram import DatagramEndpoint
from ..lowlevel.api_sync.transports import socket as _transport_socket
from ..lowlevel.socket import INETSocketAttribute, SocketAddress, SocketProxy, new_socket_address
from ..protocol import DatagramProtocol
from .abc import AbstractNetworkClient


class UDPNetworkClient(AbstractNetworkClient[_T_SentPacket, _T_ReceivedPacket]):
    """
    A network client interface for UDP communication.
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
        protocol: DatagramProtocol[_T_SentPacket, _T_ReceivedPacket],
        *,
        local_address: tuple[str, int] | None = ...,
        family: int = ...,
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
        __arg: _socket.socket | tuple[str, int],
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
            address: A pair of ``(host, port)`` for connection.
            local_address: If given, is a ``(local_host, local_port)`` tuple used to bind the socket locally.
            family: The address family. Should be any of ``AF_UNSPEC``, ``AF_INET`` or ``AF_INET6``.

        Socket Parameters:
            socket: An already connected UDP :class:`socket.socket`. If `socket` is given,
                    none of `family` and `local_address` should be specified.

        Keyword Arguments:
            retry_interval: The maximum wait time to wait for a blocking operation before retrying.
                            Set it to :data:`math.inf` to disable this feature.
        """
        super().__init__()

        socket: _socket.socket
        match __arg:
            case _socket.socket() as socket if not kwargs:
                pass
            case (str(host), int(port)):
                if (family := kwargs.get("family", _socket.AF_UNSPEC)) != _socket.AF_UNSPEC:
                    _utils.check_inet_socket_family(family)
                socket = _create_udp_socket(remote_address=(host, port), **kwargs)
            case _:
                raise TypeError("Invalid arguments")

        try:
            _utils.check_inet_socket_family(socket.family)
            _utils.check_socket_is_connected(socket)

            local_address: tuple[Any, ...] = socket.getsockname()

            transport = _transport_socket.SocketDatagramTransport(
                socket,
                retry_interval=retry_interval,
                max_datagram_size=constants.MAX_DATAGRAM_BUFSIZE,
            )
            local_address = new_socket_address(local_address, socket.family)
            if local_address.port == 0:
                raise AssertionError(f"{socket} is not bound to a local address")
        except BaseException:
            socket.close()
            raise

        self.__send_lock = _lock.ForkSafeLock(threading.Lock)
        self.__receive_lock = _lock.ForkSafeLock(threading.Lock)
        try:
            self.__endpoint: DatagramEndpoint[_T_SentPacket, _T_ReceivedPacket] = DatagramEndpoint(transport, protocol)
            self.__socket_proxy = SocketProxy(transport.extra(INETSocketAttribute.socket), lock=self.__send_lock.get)
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
                _utils.check_real_socket_state(endpoint.extra(INETSocketAttribute.socket))

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


def _create_udp_socket(
    remote_address: tuple[str, int],
    *,
    local_address: tuple[str, int] | None = None,
    family: int = _socket.AF_UNSPEC,
) -> _socket.socket:

    errors: list[OSError] = []

    for family, _, proto, _, remote_sockaddr in _socket.getaddrinfo(*remote_address, family=family, type=_socket.SOCK_DGRAM):
        try:
            socket = _socket.socket(family, _socket.SOCK_DGRAM, proto)
        except OSError as exc:
            errors.append(exc)
            continue
        except BaseException:
            errors.clear()
            raise
        try:
            if local_address is not None:
                socket.bind(local_address)

            socket.connect(remote_sockaddr)

            errors.clear()
            return socket
        except OSError as exc:
            socket.close()
            errors.append(exc)
            continue
        except BaseException:
            errors.clear()
            socket.close()
            raise

    if errors:
        try:
            raise ExceptionGroup("Could not create the UDP socket", errors)
        finally:
            errors.clear()
    else:
        remote_host = remote_address[0]
        raise OSError(f"getaddrinfo({remote_host!r}) returned empty list")
