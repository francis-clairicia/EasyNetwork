# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Network client module"""

from __future__ import annotations

__all__ = ["UDPNetworkClient", "UDPNetworkEndpoint"]

import socket as _socket
from contextlib import contextmanager
from operator import itemgetter
from threading import Lock
from time import monotonic as _time_monotonic
from typing import TYPE_CHECKING, Any, Generic, Iterator, TypeAlias, TypeVar, final, overload

from ..protocol import DatagramProtocol, DatagramProtocolParseError
from ..tools.socket import MAX_DATAGRAM_BUFSIZE, SocketAddress, SocketProxy, new_socket_address
from .abc import AbstractNetworkClient

_ReceivedPacketT = TypeVar("_ReceivedPacketT")
_SentPacketT = TypeVar("_SentPacketT")


_Address: TypeAlias = tuple[str, int] | tuple[str, int, int, int]  # type: ignore[misc]
# False positive, see https://github.com/python/mypy/issues/11098


class UDPNetworkEndpoint(Generic[_SentPacketT, _ReceivedPacketT]):
    __slots__ = (
        "__socket",
        "__socket_proxy",
        "__addr",
        "__peer",
        "__owner",
        "__closed",
        "__protocol",
        "__lock",
        "__default_send_flags",
        "__default_recv_flags",
    )

    if TYPE_CHECKING:
        __Self = TypeVar("__Self", bound="UDPNetworkEndpoint[Any, Any]")

    @overload
    def __init__(
        self,
        /,
        protocol: DatagramProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        family: int = ...,
        timeout: float | None = ...,
        remote_address: tuple[str, int] | None = ...,
        source_address: tuple[str, int] | None = ...,
        send_flags: int = ...,
        recv_flags: int = ...,
    ) -> None:
        ...

    @overload
    def __init__(
        self,
        /,
        protocol: DatagramProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        socket: _socket.socket,
        give: bool,
        send_flags: int = ...,
        recv_flags: int = ...,
    ) -> None:
        ...

    def __init__(
        self,
        /,
        protocol: DatagramProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        send_flags: int = 0,
        recv_flags: int = 0,
        **kwargs: Any,
    ) -> None:
        self.__closed: bool = True  # If any exception occurs, the client will already be in a closed state
        super().__init__()
        self.__lock = Lock()

        assert isinstance(protocol, DatagramProtocol)

        self.__protocol: DatagramProtocol[_SentPacketT, _ReceivedPacketT] = protocol

        socket: _socket.socket
        peername: SocketAddress | None = None
        external_socket: bool
        if "socket" in kwargs:
            external_socket = True
            socket = kwargs.pop("socket")
            if not isinstance(socket, _socket.socket):
                raise TypeError("Invalid arguments")
            try:
                give: bool = kwargs.pop("give")
            except KeyError:
                raise TypeError("Missing keyword argument 'give'") from None
            if kwargs:
                raise TypeError("Invalid arguments")
            if socket.family not in (_socket.AF_INET, _socket.AF_INET6):
                raise ValueError("Only AF_INET and AF_INET6 families are supported")
            self.__owner = bool(give)
        else:
            external_socket = False
            _default_timeout: Any = object()
            family = kwargs.pop("family", _socket.AF_INET)
            timeout: float | None = kwargs.pop("timeout", _default_timeout)
            remote_address: tuple[str, int] | None = kwargs.pop("remote_address", None)
            source_address: tuple[str, int] | None = kwargs.pop("source_address", None)
            if kwargs:
                raise TypeError("Invalid arguments")
            if family not in (_socket.AF_INET, _socket.AF_INET6):
                raise ValueError("Only AF_INET and AF_INET6 families are supported")
            socket = _socket.socket(family, _socket.SOCK_DGRAM)
            try:
                if source_address is None:
                    socket.bind(("", 0))
                else:
                    source_host, source_port = source_address
                    socket.bind((source_host, source_port))
                if timeout is not _default_timeout:
                    socket.settimeout(timeout)
                if remote_address is not None:
                    remote_host, remote_port = remote_address
                    socket.connect((remote_host, remote_port))
                    peername = new_socket_address(socket.getpeername(), socket.family)
            except BaseException:
                socket.close()
                raise

            self.__owner = True

        try:
            if socket.type != _socket.SOCK_DGRAM:
                raise ValueError("Invalid socket type")

            if external_socket:
                if socket.getsockname()[1] == 0:
                    socket.bind(("", 0))
                try:
                    peername = new_socket_address(socket.getpeername(), socket.family)
                except OSError:
                    peername = None

            self.__addr: SocketAddress = new_socket_address(socket.getsockname(), socket.family)
            self.__peer: SocketAddress | None = peername
            self.__socket_proxy = SocketProxy(socket)
            self.__default_send_flags: int = send_flags
            self.__default_recv_flags: int = recv_flags
        except BaseException:
            if self.__owner:
                socket.close()
            raise
        self.__socket: _socket.socket = socket
        self.__closed = False

    def __del__(self) -> None:  # pragma: no cover
        try:
            if not self.is_closed():
                self.close()
        except AttributeError:  # __init__ was probably not completed
            pass

    def __repr__(self) -> str:
        try:
            socket = self.__socket
        except AttributeError:
            return f"<{type(self).__name__} closed>"
        return f"<{type(self).__name__} socket={socket!r}>"

    def __enter__(self: __Self) -> __Self:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def __getstate__(self) -> Any:  # pragma: no cover
        raise TypeError(f"cannot pickle {self.__class__.__name__!r} object")

    @final
    def is_closed(self) -> bool:
        return self.__closed

    def close(self) -> None:
        with self.__lock:
            if self.__closed:
                return
            self.__closed = True
            socket: _socket.socket = self.__socket
            del self.__socket
            if not self.__owner:
                return
            socket.close()

    def send_packet_to(
        self,
        address: _Address | None,
        packet: _SentPacketT,
    ) -> None:
        with self.__lock:
            if self.__closed:
                raise OSError("Closed client")
            socket: _socket.socket = self.__socket
            if (remote_addr := self.__peer) is not None:
                if address is not None and new_socket_address(address, socket.family) != remote_addr:
                    raise ValueError(f"Invalid address: must be None or {remote_addr}")
                address = None
            elif address is None:
                raise ValueError("Invalid address: must not be None")
            data: bytes = self.__protocol.make_datagram(packet)
            flags: int = self.__default_send_flags
            with _restore_timeout_at_end(socket):
                socket.settimeout(None)
                if address is None:
                    socket.send(data, flags)
                else:
                    socket.sendto(data, flags, address)

    def recv_packet_from(self, timeout: float | None = None) -> tuple[_ReceivedPacketT, SocketAddress]:
        with self.__lock:
            if self.__closed:
                raise OSError("Closed client")
            flags = self.__default_recv_flags
            socket: _socket.socket = self.__socket
            socket_recvfrom = socket.recvfrom
            socket_settimeout = socket.settimeout
            remote_address: SocketAddress | None = self.__peer
            bufsize: int = MAX_DATAGRAM_BUFSIZE  # pull value to local namespace
            monotonic = _time_monotonic  # pull function to local namespace

            with _restore_timeout_at_end(socket):
                socket_settimeout(timeout)
                while True:
                    try:
                        _start = monotonic()
                        data, sender = socket_recvfrom(bufsize, flags)
                        _end = monotonic()
                    except (TimeoutError, BlockingIOError) as exc:
                        if timeout is None:  # pragma: no cover
                            raise RuntimeError("socket.recvfrom() timed out with timeout=None ?") from exc
                        break
                    sender = new_socket_address(sender, socket.family)
                    if remote_address is not None and sender != remote_address:
                        if timeout is not None:
                            if timeout == 0:
                                break
                            timeout -= _end - _start
                            if timeout < 0:  # pragma: no cover
                                timeout = 0
                            socket_settimeout(timeout)
                        continue
                    try:
                        return self.__protocol.build_packet_from_datagram(data), sender
                    except DatagramProtocolParseError:
                        raise
                    except Exception as exc:  # pragma: no cover
                        raise RuntimeError(str(exc)) from exc
                    finally:
                        del data
                # Loop break
                raise TimeoutError("recv_packet() timed out")

    def iter_received_packets_from(self, timeout: float | None = 0) -> Iterator[tuple[_ReceivedPacketT, SocketAddress]]:
        recv_packet_from = self.recv_packet_from

        while True:
            if self.__closed:
                return
            try:
                packet_tuple = recv_packet_from(timeout=timeout)
            except OSError:
                return
            yield packet_tuple  # yield out of lock scope

    def get_local_address(self) -> SocketAddress:
        return self.__addr

    def get_remote_address(self) -> SocketAddress | None:
        return self.__peer

    def fileno(self) -> int:
        with self.__lock:
            if self.__closed:
                return -1
            return self.__socket.fileno()

    @property
    @final
    def socket(self) -> SocketProxy:
        return self.__socket_proxy

    @property
    @final
    def default_send_flags(self) -> int:
        return self.__default_send_flags

    @property
    @final
    def default_recv_flags(self) -> int:
        return self.__default_recv_flags


class UDPNetworkClient(AbstractNetworkClient[_SentPacketT, _ReceivedPacketT], Generic[_SentPacketT, _ReceivedPacketT]):
    __slots__ = ("__endpoint", "__peer")

    @overload
    def __init__(
        self,
        address: tuple[str, int],
        /,
        protocol: DatagramProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        family: int = ...,
        timeout: float | None = ...,
        source_address: tuple[str, int] | None = ...,
        send_flags: int = ...,
        recv_flags: int = ...,
    ) -> None:
        ...

    @overload
    def __init__(
        self,
        socket: _socket.socket,
        /,
        protocol: DatagramProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        give: bool = ...,
        send_flags: int = ...,
        recv_flags: int = ...,
    ) -> None:
        ...

    def __init__(
        self,
        __arg: _socket.socket | tuple[str, int],
        /,
        protocol: DatagramProtocol[_SentPacketT, _ReceivedPacketT],
        **kwargs: Any,
    ) -> None:
        super().__init__()

        endpoint: UDPNetworkEndpoint[_SentPacketT, _ReceivedPacketT]
        if isinstance(__arg, _socket.socket):
            socket = __arg
            endpoint = UDPNetworkEndpoint(protocol=protocol, socket=socket, **kwargs)
        elif isinstance(__arg, tuple):
            address = __arg
            endpoint = UDPNetworkEndpoint(protocol=protocol, remote_address=address, **kwargs)
        else:
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

    @final
    def is_closed(self) -> bool:
        try:
            endpoint = self.__endpoint
        except AttributeError:  # pragma: no cover
            return True
        return endpoint.is_closed()

    def close(self) -> None:
        try:
            endpoint = self.__endpoint
        except AttributeError:  # pragma: no cover
            return
        return endpoint.close()

    def get_local_address(self) -> SocketAddress:
        return self.__endpoint.get_local_address()

    def get_remote_address(self) -> SocketAddress:
        return self.__peer

    def send_packet(self, packet: _SentPacketT) -> None:
        return self.__endpoint.send_packet_to(None, packet)

    def recv_packet(self, timeout: float | None = None) -> _ReceivedPacketT:
        return self.__endpoint.recv_packet_from(timeout=timeout)[0]

    def iter_received_packets(self, timeout: float | None = 0) -> Iterator[_ReceivedPacketT]:
        return map(itemgetter(0), self.__endpoint.iter_received_packets_from(timeout=timeout))

    def fileno(self) -> int:
        return self.__endpoint.fileno()

    @property
    @final
    def socket(self) -> SocketProxy:
        return self.__endpoint.socket

    @property
    @final
    def default_send_flags(self) -> int:
        return self.__endpoint.default_send_flags

    @property
    @final
    def default_recv_flags(self) -> int:
        return self.__endpoint.default_recv_flags


@contextmanager
def _restore_timeout_at_end(socket: _socket.socket) -> Iterator[float | None]:
    old_timeout: float | None = socket.gettimeout()
    try:
        yield old_timeout
    finally:
        socket.settimeout(old_timeout)
