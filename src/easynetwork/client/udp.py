# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Network client module"""

from __future__ import annotations

__all__ = ["UDPNetworkClient", "UDPNetworkEndpoint"]

import socket as _socket
from operator import itemgetter as _itemgetter
from threading import Lock as _Lock
from typing import TYPE_CHECKING, Any, Generic, Iterator, TypeAlias, TypeVar, final, overload

from ..protocol import DatagramProtocol, DatagramProtocolParseError
from ..tools._utils import check_real_socket_state as _check_real_socket_state, restore_timeout_at_end as _restore_timeout_at_end
from ..tools.socket import MAX_DATAGRAM_BUFSIZE, SocketAddress, SocketProxy, new_socket_address
from .abc import AbstractNetworkClient
from .exceptions import ClientClosedError

if TYPE_CHECKING:
    from types import TracebackType

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
        "__protocol",
        "__lock",
        "__weakref__",
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
        remote_address: tuple[str, int] | None = ...,
        source_address: tuple[str, int] | None = ...,
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
    ) -> None:
        ...

    def __init__(
        self,
        /,
        protocol: DatagramProtocol[_SentPacketT, _ReceivedPacketT],
        **kwargs: Any,
    ) -> None:
        self.__socket: _socket.socket | None = None  # If any exception occurs, the client will already be in a closed state
        super().__init__()
        self.__lock = _Lock()

        assert isinstance(protocol, DatagramProtocol)

        self.__protocol: DatagramProtocol[_SentPacketT, _ReceivedPacketT] = protocol

        socket: _socket.socket
        peername: SocketAddress | None = None
        external_socket: bool
        if "socket" in kwargs:
            external_socket = True
            socket = kwargs.pop("socket")
            if not isinstance(socket, _socket.socket):  # pragma: no cover
                raise TypeError("Invalid arguments")
            try:
                give: bool = kwargs.pop("give")
            except KeyError:
                raise TypeError("Missing keyword argument 'give'") from None
            if kwargs:  # pragma: no cover
                raise TypeError("Invalid arguments")
            if socket.family not in (_socket.AF_INET, _socket.AF_INET6):
                raise ValueError("Only AF_INET and AF_INET6 families are supported")
            self.__owner = bool(give)
        else:
            external_socket = False
            family = kwargs.pop("family", _socket.AF_INET)
            remote_address: tuple[str, int] | None = kwargs.pop("remote_address", None)
            source_address: tuple[str, int] | None = kwargs.pop("source_address", None)
            if kwargs:  # pragma: no cover
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
            self.__socket_proxy = SocketProxy(socket, lock=self.__lock)
        except BaseException:
            if self.__owner:
                socket.close()
            raise
        self.__socket = socket

    def __del__(self) -> None:  # pragma: no cover
        try:
            socket: _socket.socket | None = self.__socket
            owner: bool = self.__owner
        except AttributeError:
            return
        if owner and socket is not None:
            socket.close()

    def __repr__(self) -> str:
        try:
            socket = self.__socket
        except AttributeError:
            return f"<{type(self).__name__} closed>"
        return f"<{type(self).__name__} socket={socket!r}>"

    def __enter__(self: __Self) -> __Self:
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None) -> None:
        self.close()

    def __getstate__(self) -> Any:  # pragma: no cover
        raise TypeError(f"cannot pickle {self.__class__.__name__!r} object")

    @final
    def is_closed(self) -> bool:
        with self.__lock:
            return self.__socket is None

    def close(self) -> None:
        with self.__lock:
            if (socket := self.__socket) is None:
                return
            self.__socket = None
            if not self.__owner:
                return
            socket.close()

    def send_packet_to(
        self,
        packet: _SentPacketT,
        address: _Address | None,
    ) -> None:
        with self.__lock:
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
            with _restore_timeout_at_end(socket):
                socket.settimeout(None)
                if address is None:
                    socket.send(data)
                else:
                    socket.sendto(data, address)
                _check_real_socket_state(socket)

    def recv_packet_from(self, timeout: float | None = None) -> tuple[_ReceivedPacketT, SocketAddress]:
        with self.__lock:
            if (socket := self.__socket) is None:
                raise ClientClosedError("Closed client")
            with _restore_timeout_at_end(socket):
                socket.settimeout(timeout)
                try:
                    data, sender = socket.recvfrom(MAX_DATAGRAM_BUFSIZE)
                except (TimeoutError, BlockingIOError) as exc:
                    if timeout is None:  # pragma: no cover
                        raise RuntimeError("socket.recvfrom() timed out with timeout=None ?") from exc
                    raise TimeoutError("recv_packet() timed out") from None
                try:
                    return self.__protocol.build_packet_from_datagram(data), new_socket_address(sender, socket.family)
                except DatagramProtocolParseError:
                    raise
                except Exception as exc:  # pragma: no cover
                    raise RuntimeError(str(exc)) from exc
                finally:
                    del data

    def iter_received_packets_from(self, timeout: float | None = 0) -> Iterator[tuple[_ReceivedPacketT, SocketAddress]]:
        recv_packet_from = self.recv_packet_from

        while True:
            if self.__socket is None:
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
            if (socket := self.__socket) is None:
                return -1
            return socket.fileno()

    @property
    @final
    def socket(self) -> SocketProxy:
        return self.__socket_proxy


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
        source_address: tuple[str, int] | None = ...,
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
            raise TypeError("Invalid arguments")  # pragma: no cover

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
        return self.__endpoint.send_packet_to(packet, None)

    def recv_packet(self, timeout: float | None = None) -> _ReceivedPacketT:
        packet, _ = self.__endpoint.recv_packet_from(timeout=timeout)
        return packet

    def iter_received_packets(self, timeout: float | None = 0) -> Iterator[_ReceivedPacketT]:
        return map(_itemgetter(0), self.__endpoint.iter_received_packets_from(timeout=timeout))

    def fileno(self) -> int:
        return self.__endpoint.fileno()

    @property
    @final
    def socket(self) -> SocketProxy:
        return self.__endpoint.socket
