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
"""UDP Network client implementation module"""

from __future__ import annotations

__all__ = ["UDPNetworkClient"]

import contextlib
import socket as _socket
from collections.abc import Iterator
from typing import Any, final, overload

from ..._typevars import _ReceivedPacketT, _SentPacketT
from ...exceptions import ClientClosedError
from ...lowlevel import _lock, _utils, constants
from ...lowlevel.api_sync.endpoints.datagram import DatagramEndpoint
from ...lowlevel.api_sync.transports.socket import SocketDatagramTransport
from ...lowlevel.socket import INETSocketAttribute, SocketAddress, SocketProxy, new_socket_address
from ...protocol import DatagramProtocol
from .abc import AbstractNetworkClient


class UDPNetworkClient(AbstractNetworkClient[_SentPacketT, _ReceivedPacketT]):
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
        protocol: DatagramProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        local_address: tuple[str, int] | None = ...,
        reuse_port: bool = ...,
        retry_interval: float = ...,
    ) -> None:
        ...

    @overload
    def __init__(
        self,
        socket: _socket.socket,
        /,
        protocol: DatagramProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        retry_interval: float = ...,
    ) -> None:
        ...

    def __init__(
        self,
        __arg: _socket.socket | tuple[str, int],
        /,
        protocol: DatagramProtocol[_SentPacketT, _ReceivedPacketT],
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
            reuse_port: Tells the kernel to allow this endpoint to be bound to the same port as other existing
                        endpoints are bound to, so long as they all set this flag when being created.
                        This option is not supported on Windows and some Unixes.
                        If the SO_REUSEPORT constant is not defined then this capability is unsupported.

        Socket Parameters:
            socket: An already connected UDP :class:`socket.socket`. If `socket` is given,
                    none of and `local_address` and `reuse_port` should be specified.

        Keyword Arguments:
            retry_interval: The maximum wait time to wait for a blocking operation before retrying.
                            Set it to :data:`math.inf` to disable this feature.
        """
        super().__init__()

        socket: _socket.socket
        match __arg:
            case _socket.socket() as socket if not kwargs:
                _utils.ensure_datagram_socket_bound(socket)
            case (str(host), int(port)):
                socket = _create_udp_socket(remote_address=(host, port), **kwargs)
            case _:  # pragma: no cover
                raise TypeError("Invalid arguments")

        try:
            _utils.check_socket_family(socket.family)
            _utils.check_socket_is_connected(socket)

            transport = SocketDatagramTransport(
                socket,
                retry_interval=retry_interval,
                max_datagram_size=constants.MAX_DATAGRAM_BUFSIZE,
            )
        except BaseException:
            socket.close()
            raise

        self.__send_lock = _lock.ForkSafeLock()
        self.__receive_lock = _lock.ForkSafeLock()
        try:
            self.__endpoint: DatagramEndpoint[_SentPacketT, _ReceivedPacketT] = DatagramEndpoint(transport, protocol)
            self.__socket_proxy = SocketProxy(transport.extra(INETSocketAttribute.socket), lock=self.__send_lock.get)
        except BaseException:
            transport.close()
            raise

    def __repr__(self) -> str:
        try:
            return f"<{type(self).__name__} endpoint={self.__endpoint!r}>"
        except AttributeError:
            return f"<{type(self).__name__} (partially initialized)>"

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
                raise ClientClosedError("Closed client")
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
                raise ClientClosedError("Closed client")
            remote_address = endpoint.extra(INETSocketAttribute.peername)
            address_family = endpoint.extra(INETSocketAttribute.family)
            return new_socket_address(remote_address, address_family)

    def send_packet(self, packet: _SentPacketT, *, timeout: float | None = None) -> None:
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
                raise ClientClosedError("Closed client")
            with self.__convert_socket_error():
                endpoint.send_packet(packet, timeout=timeout)
                _utils.check_real_socket_state(endpoint.extra(INETSocketAttribute.socket))

    def recv_packet(self, *, timeout: float | None = None) -> _ReceivedPacketT:
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
                raise ClientClosedError("Closed client")
            with self.__convert_socket_error():
                return endpoint.recv_packet(timeout=timeout)

    @contextlib.contextmanager
    def __convert_socket_error(self) -> Iterator[None]:
        try:
            yield
        except OSError as exc:
            if exc.errno in constants.CLOSED_SOCKET_ERRNOS:
                raise ClientClosedError("Closed client") from exc
            raise

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
    *,
    local_address: tuple[str, int] | None = None,
    remote_address: tuple[str, int] | None = None,
    reuse_port: bool = False,
) -> _socket.socket:
    local_host: str | None
    local_port: int
    if local_address is None:
        local_host = "localhost"
        local_port = 0
        local_address = (local_host, local_port)
    else:
        local_host, local_port = local_address

    flags: int = 0
    if not remote_address:
        flags |= _socket.AI_PASSIVE

    errors: list[OSError] = []

    for family, _, proto, _, sockaddr in _socket.getaddrinfo(
        *(remote_address or local_address),
        family=_socket.AF_UNSPEC,
        type=_socket.SOCK_DGRAM,
        flags=flags,
    ):
        try:
            socket = _socket.socket(family, _socket.SOCK_DGRAM, proto)
        except OSError as exc:
            errors.append(exc)
            continue
        except BaseException:
            errors.clear()
            raise
        try:
            if reuse_port:
                _utils.set_reuseport(socket)

            if remote_address is None:
                local_sockaddr = sockaddr
                remote_sockaddr = None
            else:
                local_sockaddr = local_address
                remote_sockaddr = sockaddr

            del sockaddr

            try:
                socket.bind(local_sockaddr)
            except OSError as exc:
                msg = f"error while attempting to bind to address {local_sockaddr!r}: {exc.strerror.lower()}"
                raise OSError(exc.errno, msg).with_traceback(exc.__traceback__) from None
            if remote_sockaddr:
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
    elif remote_address is not None:
        remote_host = remote_address[0]
        raise OSError(f"getaddrinfo({remote_host!r}) returned empty list")
    else:
        raise OSError(f"getaddrinfo({local_host!r}) returned empty list")
