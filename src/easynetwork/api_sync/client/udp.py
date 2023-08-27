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

__all__ = ["UDPNetworkClient", "UDPNetworkEndpoint"]

import contextlib as _contextlib
import errno as _errno
import math
import socket as _socket
import threading
import time
from collections.abc import Iterator
from operator import itemgetter as _itemgetter
from typing import TYPE_CHECKING, Any, Generic, Self, final, overload

from ..._typevars import _ReceivedPacketT, _SentPacketT
from ...exceptions import ClientClosedError, DatagramProtocolParseError
from ...protocol import DatagramProtocol
from ...tools._lock import ForkSafeLock
from ...tools._utils import (
    check_real_socket_state as _check_real_socket_state,
    check_socket_family as _check_socket_family,
    check_socket_no_ssl as _check_socket_no_ssl,
    ensure_datagram_socket_bound as _ensure_datagram_socket_bound,
    error_from_errno as _error_from_errno,
    lock_with_timeout as _lock_with_timeout,
    retry_socket_method as _retry_socket_method,
    set_reuseport as _set_reuseport,
    validate_timeout_delay as _validate_timeout_delay,
)
from ...tools.constants import CLOSED_SOCKET_ERRNOS, MAX_DATAGRAM_BUFSIZE
from ...tools.socket import SocketAddress, SocketProxy, new_socket_address
from .abc import AbstractNetworkClient

if TYPE_CHECKING:
    from types import TracebackType


class UDPNetworkEndpoint(Generic[_SentPacketT, _ReceivedPacketT]):
    """Generic UDP endpoint interface."""

    __slots__ = (
        "__socket",
        "__socket_proxy",
        "__addr",
        "__peer",
        "__protocol",
        "__send_lock",
        "__receive_lock",
        "__socket_lock",
        "__retry_interval",
        "__weakref__",
    )

    @overload
    def __init__(
        self,
        protocol: DatagramProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        local_address: tuple[str, int] | None = ...,
        remote_address: tuple[str, int] | None = ...,
        reuse_port: bool = ...,
        retry_interval: float = ...,
    ) -> None:
        ...

    @overload
    def __init__(
        self,
        protocol: DatagramProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        socket: _socket.socket,
        retry_interval: float = ...,
    ) -> None:
        ...

    def __init__(
        self,
        protocol: DatagramProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        retry_interval: float = 1.0,
        **kwargs: Any,
    ) -> None:
        """
        Common Parameters:
            protocol: The :term:`protocol object` to use.

        Connection Parameters:
            remote_address: If given, is a ``(host, port)`` tuple used to connect the socket.
            local_address: If given, is a ``(local_host, local_port)`` tuple used to bind the socket locally.
            reuse_port: Tells the kernel to allow this endpoint to be bound to the same port as other existing
                        endpoints are bound to, so long as they all set this flag when being created.
                        This option is not supported on Windows and some Unixes.
                        If the SO_REUSEPORT constant is not defined then this capability is unsupported.

        Socket Parameters:
            socket: An already connected UDP :class:`socket.socket`. If `socket` is given,
                    none of and `local_address`, `remote_address` and `reuse_port` should be specified.

        Keyword Arguments:
            retry_interval: The maximum wait time to wait for a blocking operation before retrying.
                            Set it to :data:`math.inf` to disable this feature.
        """
        self.__socket: _socket.socket | None = None  # If any exception occurs, the client will already be in a closed state
        super().__init__()

        if not isinstance(protocol, DatagramProtocol):
            raise TypeError(f"Expected a DatagramProtocol object, got {protocol!r}")

        self.__protocol: DatagramProtocol[_SentPacketT, _ReceivedPacketT] = protocol

        self.__retry_interval: float | None
        self.__retry_interval = retry_interval = _validate_timeout_delay(float(retry_interval), positive_check=False)
        if self.__retry_interval <= 0:
            raise ValueError("retry_interval must be a strictly positive float")
        if math.isinf(self.__retry_interval):
            self.__retry_interval = None

        socket: _socket.socket
        external_socket: bool
        match kwargs:
            case {"socket": _socket.socket() as socket, **remainder} if not remainder:
                external_socket = True
            case _ if "socket" not in kwargs:
                external_socket = False
                socket = _create_udp_socket(**kwargs)
            case _:  # pragma: no cover
                raise TypeError("Invalid arguments")

        try:
            if socket.type != _socket.SOCK_DGRAM:
                raise ValueError("Invalid socket type")

            _check_socket_no_ssl(socket)
            _check_socket_family(socket.family)
            if external_socket:
                _ensure_datagram_socket_bound(socket)
            try:
                peername = new_socket_address(socket.getpeername(), socket.family)
            except OSError:
                peername = None

            # Do not use global default timeout here
            socket.settimeout(0)

            self.__addr: SocketAddress = new_socket_address(socket.getsockname(), socket.family)
            self.__peer: SocketAddress | None = peername

            self.__send_lock = ForkSafeLock(threading.Lock)
            self.__receive_lock = ForkSafeLock(threading.Lock)
            self.__socket_lock = ForkSafeLock(threading.Lock)

            self.__socket_proxy = SocketProxy(socket, lock=self.__socket_lock.get)
        except BaseException:
            socket.close()
            raise
        self.__socket = socket

    def __del__(self) -> None:  # pragma: no cover
        try:
            socket: _socket.socket | None = self.__socket
        except AttributeError:
            return
        if socket is not None:
            socket.close()

    def __repr__(self) -> str:
        try:
            socket = self.__socket
        except AttributeError:
            return f"<{type(self).__name__} closed>"
        return f"<{type(self).__name__} socket={socket!r}>"

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None) -> None:
        """
        Calls :meth:`close`.
        """
        self.close()

    def __getstate__(self) -> Any:  # pragma: no cover
        raise TypeError(f"cannot pickle {self.__class__.__name__!r} object")

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
            if (socket := self.__socket) is None:
                return
            self.__socket = None
            socket.close()

    def send_packet_to(
        self,
        packet: _SentPacketT,
        address: tuple[str, int] | tuple[str, int, int, int] | None,
        *,
        timeout: float | None = None,
    ) -> None:
        """
        Sends `packet` to the remote endpoint `address`. Thread-safe.

        If a remote address is configured, `address` must be :data:`None` or the same as the remote address,
        otherwise `address` must not be :data:`None`.

        If `timeout` is not :data:`None`, the entire send operation will take at most `timeout` seconds.

        Caution:
            A timeout on a send operation is unusual.

            In the case of a timeout, it is impossible to know if all the packet data has been sent.

        Important:
            The lock acquisition time is included in the `timeout`.

            This means that you may get a :exc:`TimeoutError` because it took too long to get the lock.

        Arguments:
            packet: the Python object to send.
            timeout: the allowed time (in seconds) for blocking operations.

        Raises:
            ClientClosedError: the client object is closed.
            TimeoutError: the send operation does not end up after `timeout` seconds.
            OSError: Unrelated OS error happen. You should check :attr:`OSError.errno`.
            ValueError: Invalid `address` value.
        """
        with (
            _lock_with_timeout(self.__send_lock.get(), timeout, error_message="send_packet() timed out") as timeout,
            self.__convert_socket_error(),
        ):
            if (socket := self.__socket) is None:
                raise ClientClosedError("Closed client")
            if (remote_addr := self.__peer) is not None:
                if address is not None:
                    if new_socket_address(address, socket.family) != remote_addr:
                        raise ValueError(f"Invalid address: must be None or {remote_addr}")
                    address = None
            elif address is None:
                raise ValueError("Invalid address: must not be None")
            data: bytes = self.__protocol.make_datagram(packet)
            retry_interval: float | None = self.__retry_interval
            try:
                if address is None:
                    _retry_socket_method(socket, timeout, retry_interval, "write", socket.send, data)
                else:
                    _retry_socket_method(socket, timeout, retry_interval, "write", socket.sendto, data, address)
                _check_real_socket_state(socket)
            except TimeoutError:
                raise TimeoutError("send_packet() timed out") from None
            finally:
                del data

    def recv_packet_from(self, *, timeout: float | None = None) -> tuple[_ReceivedPacketT, SocketAddress]:
        """
        Waits for a new packet to arrive from another endpoint. Thread-safe.

        If `timeout` is not :data:`None`, the entire receive operation will take at most `timeout` seconds.

        Important:
            The lock acquisition time is included in the `timeout`.

            This means that you may get a :exc:`TimeoutError` because it took too long to get the lock.

        Arguments:
            timeout: the allowed time (in seconds) for blocking operations.

        Raises:
            ClientClosedError: the client object is closed.
            TimeoutError: the receive operation does not end up after `timeout` seconds.
            OSError: Unrelated OS error happen. You should check :attr:`OSError.errno`.

        Returns:
            A ``(packet, address)`` tuple, where `address` is the endpoint that delivered this packet.
        """
        with (
            _lock_with_timeout(self.__receive_lock.get(), timeout, error_message="recv_packet() timed out") as timeout,
            self.__convert_socket_error(),
        ):
            if (socket := self.__socket) is None:
                raise ClientClosedError("Closed client")
            retry_interval: float | None = self.__retry_interval
            bufsize: int = MAX_DATAGRAM_BUFSIZE
            try:
                data, sender = _retry_socket_method(socket, timeout, retry_interval, "read", socket.recvfrom, bufsize)
            except TimeoutError:
                raise TimeoutError("recv_packet() timed out") from None
            sender = new_socket_address(sender, socket.family)
            try:
                return self.__protocol.build_packet_from_datagram(data), sender
            except DatagramProtocolParseError as exc:
                exc.sender_address = sender
                raise
            finally:
                del data

    def iter_received_packets_from(self, *, timeout: float | None = 0) -> Iterator[tuple[_ReceivedPacketT, SocketAddress]]:
        """
        Returns an iterator that waits for a new packet to arrive from another endpoint.

        If `timeout` is not :data:`None`, the entire receive operation will take at most `timeout` seconds; it defaults to zero.

        Important:
            The `timeout` is for the entire iterator::

                iterator = endpoint.iter_received_packets_from(timeout=10)

                # Let's say that this call took 6 seconds...
                first_packet = next(iterator)

                # ...then this call has a maximum of 4 seconds, not 10.
                second_packet = next(iterator)

            The time taken outside the iterator object is not decremented to the timeout parameter.

        Arguments:
            timeout: the allowed time (in seconds) for all the receive operations.

        Yields:
            A ``(packet, address)`` tuple, where `address` is the endpoint that delivered this packet.
        """
        perf_counter = time.perf_counter
        while True:
            try:
                _start = perf_counter()
                packet_tuple = self.recv_packet_from(timeout=timeout)
                _end = perf_counter()
            except OSError:
                return
            yield packet_tuple
            if timeout is not None:
                timeout -= _end - _start

    @_contextlib.contextmanager
    def __convert_socket_error(self) -> Iterator[None]:
        try:
            yield
        except OSError as exc:
            if exc.errno in CLOSED_SOCKET_ERRNOS:
                raise _error_from_errno(_errno.ECONNABORTED) from exc
            raise

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

    def get_remote_address(self) -> SocketAddress | None:
        """
        Returns the remote socket IP address. Thread-safe.

        Raises:
            ClientClosedError: the client object is closed.
            OSError: Unrelated OS error happen. You should check :attr:`OSError.errno`.

        Returns:
            the client's remote address if configured, :data:`None` otherwise.
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

    @property
    @final
    def socket(self) -> SocketProxy:
        """A view to the underlying socket instance. Read-only attribute."""
        return self.__socket_proxy


class UDPNetworkClient(AbstractNetworkClient[_SentPacketT, _ReceivedPacketT]):
    """
    A network client interface for UDP communication.
    """

    __slots__ = ("__endpoint", "__peer")

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

        endpoint: UDPNetworkEndpoint[_SentPacketT, _ReceivedPacketT]
        match __arg:
            case _socket.socket() as socket:
                endpoint = UDPNetworkEndpoint(protocol=protocol, socket=socket, **kwargs)
            case tuple() as address:
                endpoint = UDPNetworkEndpoint(protocol=protocol, remote_address=address, **kwargs)
            case _:  # pragma: no cover
                raise TypeError("Invalid arguments")

        try:
            self.__endpoint: UDPNetworkEndpoint[_SentPacketT, _ReceivedPacketT] = endpoint
            remote_address = endpoint.get_remote_address()
            if remote_address is None:
                raise OSError("No remote address configured")
            self.__peer: SocketAddress = remote_address
        except BaseException:
            endpoint.close()
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
        try:
            endpoint = self.__endpoint
        except AttributeError:  # pragma: no cover
            return True
        return endpoint.is_closed()

    def close(self) -> None:
        """
        Close the client. Thread-safe.

        Once that happens, all future operations on the client object will raise a :exc:`.ClientClosedError`.
        The remote end will receive no more data (after queued data is flushed).

        Can be safely called multiple times.

        Raises:
            OSError: Unrelated OS error happen. You should check :attr:`OSError.errno`.
        """
        try:
            endpoint = self.__endpoint
        except AttributeError:  # pragma: no cover
            return
        return endpoint.close()

    def get_local_address(self) -> SocketAddress:
        """
        Returns the local socket IP address. Thread-safe.

        Raises:
            ClientClosedError: the client object is closed.
            OSError: Unrelated OS error happen. You should check :attr:`OSError.errno`.

        Returns:
            the client's local address.
        """
        return self.__endpoint.get_local_address()

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

    def send_packet(self, packet: _SentPacketT, *, timeout: float | None = None) -> None:
        """
        Sends `packet` to the remote endpoint. Thread-safe.

        If `timeout` is not :data:`None`, the entire send operation will take at most `timeout` seconds.

        Caution:
            A timeout on a send operation is unusual.

            In the case of a timeout, it is impossible to know if all the packet data has been sent.

        Important:
            The lock acquisition time is included in the `timeout`.

            This means that you may get a :exc:`TimeoutError` because it took too long to get the lock.

        Arguments:
            packet: the Python object to send.
            timeout: the allowed time (in seconds) for blocking operations.

        Raises:
            ClientClosedError: the client object is closed.
            TimeoutError: the send operation does not end up after `timeout` seconds.
            OSError: Unrelated OS error happen. You should check :attr:`OSError.errno`.
        """
        return self.__endpoint.send_packet_to(packet, None, timeout=timeout)

    def recv_packet(self, *, timeout: float | None = None) -> _ReceivedPacketT:
        """
        Waits for a new packet from the remote endpoint. Thread-safe.

        If `timeout` is not :data:`None`, the entire receive operation will take at most `timeout` seconds.

        Important:
            The lock acquisition time is included in the `timeout`.

            This means that you may get a :exc:`TimeoutError` because it took too long to get the lock.

        Arguments:
            timeout: the allowed time (in seconds) for blocking operations.

        Raises:
            ClientClosedError: the client object is closed.
            TimeoutError: the receive operation does not end up after `timeout` seconds.
            OSError: Unrelated OS error happen. You should check :attr:`OSError.errno`.

        Returns:
            the received packet.
        """
        packet, _ = self.__endpoint.recv_packet_from(timeout=timeout)
        return packet

    def iter_received_packets(self, *, timeout: float | None = 0) -> Iterator[_ReceivedPacketT]:
        return map(_itemgetter(0), self.__endpoint.iter_received_packets_from(timeout=timeout))

    iter_received_packets.__doc__ = AbstractNetworkClient.iter_received_packets.__doc__

    def fileno(self) -> int:
        """
        Returns the socket's file descriptor, or ``-1`` if the client (or the socket) is closed. Thread-safe.

        Returns:
            the opened file descriptor.
        """
        return self.__endpoint.fileno()

    @property
    @final
    def socket(self) -> SocketProxy:
        """A view to the underlying socket instance. Read-only attribute."""
        return self.__endpoint.socket


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
                _set_reuseport(socket)

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
