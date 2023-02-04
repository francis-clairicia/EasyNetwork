# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Network client module"""

from __future__ import annotations

__all__ = ["UDPNetworkClient", "UDPNetworkEndpoint"]

from collections import deque
from contextlib import contextmanager
from operator import itemgetter
from socket import socket as Socket
from threading import RLock
from typing import TYPE_CHECKING, Any, Callable, Generic, Iterator, ParamSpec, TypeAlias, TypeVar, final, overload

from ..protocol import DatagramProtocol, DatagramProtocolParseError
from ..tools.socket import AddressFamily, SocketAddress, new_socket_address
from .abc import AbstractNetworkClient

_P = ParamSpec("_P")
_T = TypeVar("_T")
_ReceivedPacketT = TypeVar("_ReceivedPacketT")
_SentPacketT = TypeVar("_SentPacketT")


_Address: TypeAlias = tuple[str, int] | tuple[str, int, int, int]  # type: ignore[misc]
# False positive, see https://github.com/python/mypy/issues/11098


_NO_DEFAULT: Any = object()


class UDPNetworkEndpoint(Generic[_SentPacketT, _ReceivedPacketT]):
    __slots__ = (
        "__socket",
        "__peer",
        "__owner",
        "__closed",
        "__protocol",
        "__packets_to_send",
        "__received_datagrams",
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
        socket: Socket,
        give: bool = ...,
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
        super().__init__()

        assert isinstance(protocol, DatagramProtocol)
        send_flags = int(send_flags)
        recv_flags = int(recv_flags)

        self.__protocol: DatagramProtocol[_SentPacketT, _ReceivedPacketT] = protocol
        self.__packets_to_send: deque[tuple[_SentPacketT, _Address]] = deque()
        self.__received_datagrams: deque[tuple[bytes, SocketAddress]] = deque()

        from socket import AF_INET, SOCK_DGRAM

        socket: Socket
        peername: SocketAddress | None = None
        if "socket" in kwargs:
            socket = kwargs.pop("socket")
            if not isinstance(socket, Socket):
                raise TypeError("Invalid arguments")
            give: bool = kwargs.pop("give", False)
            if kwargs:
                raise TypeError("Invalid arguments")
            self.__owner = bool(give)
            if socket.getsockname()[1] == 0:
                socket.bind(("", 0))
            try:
                peername = new_socket_address(socket.getpeername(), socket.family)
            except OSError:
                peername = None
        else:
            _default_timeout: Any = object()

            family = AddressFamily(kwargs.pop("family", AF_INET))
            timeout: float | None = kwargs.pop("timeout", _default_timeout)
            remote_address: tuple[str, int] | None = kwargs.pop("remote_address", None)
            source_address: tuple[str, int] | None = kwargs.pop("source_address", None)
            if kwargs:
                raise TypeError("Invalid arguments")
            socket = Socket(family, SOCK_DGRAM)
            try:
                if source_address is None:
                    socket.bind(("", 0))
                else:
                    socket.bind(source_address)
                if timeout is not _default_timeout:
                    socket.settimeout(timeout)
                if remote_address is not None:
                    socket.connect(remote_address)
                    peername = new_socket_address(socket.getpeername(), socket.family)
            except BaseException:
                socket.close()
                raise

            self.__owner = True

        if socket.type != SOCK_DGRAM:
            raise ValueError("Invalid socket type")

        socket.settimeout(None)

        self.__peer: SocketAddress | None = peername
        self.__closed: bool = False
        self.__socket: Socket = socket
        self.__lock: RLock = RLock()
        self.__default_send_flags: int = send_flags
        self.__default_recv_flags: int = recv_flags

    def __del__(self) -> None:  # pragma: no cover
        try:
            if not self.is_closed():
                self.close()
        except AttributeError:  # __init__ was probably not completed
            pass

    def __enter__(self: __Self) -> __Self:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    @final
    def is_closed(self) -> bool:
        return self.__closed

    def close(self) -> None:
        with self.__lock:
            if self.__closed:
                return
            self.__closed = True
            self.__peer = None
            socket: Socket = self.__socket
            del self.__socket
            if not self.__owner:
                return
            socket.close()

    def send_packet(
        self,
        address: _Address | None,
        packet: _SentPacketT,
    ) -> None:
        with self.__lock:
            self._check_not_closed()
            address = self._verify_address(address)
            self.__packets_to_send.append((packet, address))
            self.__write_on_socket()

    def send_packets(
        self,
        address: _Address | None,
        *packets: _SentPacketT,
    ) -> None:
        if not packets:
            return
        with self.__lock:
            self._check_not_closed()
            address = self._verify_address(address)
            self.__packets_to_send.extend((packet, address) for packet in packets)
            self.__write_on_socket()

    def _verify_address(self, address: _Address | None) -> _Address:
        if remote_addr := self.__peer:
            if address not in (None, remote_addr):
                raise ValueError(f"Invalid address: must be None or {remote_addr}")
            return remote_addr
        if address is None:
            raise ValueError("Invalid address: must not be None")
        return address

    def __write_on_socket(self) -> None:
        flags = self.__default_send_flags
        socket = self.__socket
        ensure_send = UDPNetworkEndpoint._ensure_send
        with _use_timeout(socket, None):
            if self.__peer:
                for data, _ in self.__produce_datagrams():
                    ensure_send(socket.send, data, flags)
            else:
                for data, address in self.__produce_datagrams():
                    ensure_send(socket.sendto, data, flags, address)  # type: ignore[call-arg, arg-type]

    @staticmethod
    def _ensure_send(send_callback: Callable[_P, int], /, *args: _P.args, **kwargs: _P.kwargs) -> None:
        while True:
            try:
                nb_bytes_sent: int = send_callback(*args, **kwargs)
                if nb_bytes_sent > 0:
                    return
            except (BlockingIOError, InterruptedError):
                pass

    def __produce_datagrams(self) -> Iterator[tuple[bytes, _Address]]:
        queue = self.__packets_to_send
        make_datagram = self.__protocol.make_datagram
        while queue:
            packet, address = queue.popleft()
            yield make_datagram(packet), address

    def recv_packet(self) -> tuple[_ReceivedPacketT, SocketAddress]:
        with self.__lock:
            self._check_not_closed()
            recv_packets_from_socket = self.__recv_packets_from_socket
            next_packet = self.__next_packet
            while True:
                try:
                    return next_packet()
                except StopIteration:
                    pass
                while not recv_packets_from_socket(timeout=None):
                    continue

    @overload
    def recv_packet_no_block(self, *, timeout: float = ...) -> tuple[_ReceivedPacketT, SocketAddress]:
        ...

    @overload
    def recv_packet_no_block(self, *, default: _T, timeout: float = ...) -> tuple[_ReceivedPacketT, SocketAddress] | _T:
        ...

    def recv_packet_no_block(
        self,
        *,
        default: _T = _NO_DEFAULT,
        timeout: float = 0,
    ) -> tuple[_ReceivedPacketT, SocketAddress] | _T:
        timeout = float(timeout)
        next_packet = self.__next_packet
        with self.__lock:
            self._check_not_closed()
            try:
                return next_packet()
            except StopIteration:
                pass
            recv_packets_from_socket = self.__recv_packets_from_socket
            while recv_packets_from_socket(timeout=timeout):
                try:
                    return next_packet()
                except StopIteration:
                    pass
            if default is not _NO_DEFAULT:
                return default
            raise TimeoutError("recv_packet() timed out")

    def iter_received_packets(
        self,
        *,
        timeout: float = 0,
    ) -> Iterator[tuple[_ReceivedPacketT, SocketAddress]]:
        timeout = float(timeout)
        recv_packets_from_socket = self.__recv_packets_from_socket
        next_packet_or_default = self.__next_packet_or_default
        check_not_closed = self._check_not_closed
        lock = self.__lock

        while True:
            with lock:
                check_not_closed()
                while (packet_tuple := next_packet_or_default(None)) is None:
                    if not recv_packets_from_socket(timeout=timeout):
                        return
                    continue
            yield packet_tuple  # yield out of lock scope

    def __recv_packets_from_socket(self, *, timeout: float | None) -> bool:
        flags = self.__default_recv_flags

        socket: Socket = self.__socket
        remote_address: SocketAddress | None = self.__peer

        with _use_timeout(socket, timeout):
            try:
                data, sender = socket.recvfrom(65536, flags)
            except (TimeoutError, BlockingIOError, InterruptedError):
                return False
            sender = new_socket_address(sender, socket.family)
            if remote_address is not None and sender != remote_address:
                return False
            self.__received_datagrams.append((data, sender))
            return True

    def __next_packet(self) -> tuple[_ReceivedPacketT, SocketAddress]:
        queue = self.__received_datagrams
        if not queue:
            raise StopIteration
        data, sender = queue.popleft()
        try:
            return self.__protocol.build_packet_from_datagram(data), sender
        except DatagramProtocolParseError:
            raise
        except Exception as exc:
            raise RuntimeError(str(exc)) from exc

    def __next_packet_or_default(self, default: _T) -> tuple[_ReceivedPacketT, SocketAddress] | _T:
        try:
            return self.__next_packet()
        except StopIteration:
            return default

    def get_local_address(self) -> SocketAddress:
        with self.__lock:
            self._check_not_closed()
            return new_socket_address(self.__socket.getsockname(), self.__socket.family)

    def get_remote_address(self) -> SocketAddress | None:
        with self.__lock:
            self._check_not_closed()
            return self.__peer

    def fileno(self) -> int:
        with self.__lock:
            if self.__closed:
                return -1
            return self.__socket.fileno()

    def dup(self) -> Socket:
        with self.__lock:
            self._check_not_closed()
            socket: Socket = self.__socket
            return socket.dup()

    @overload
    def getsockopt(self, __level: int, __optname: int, /) -> int:
        ...

    @overload
    def getsockopt(self, __level: int, __optname: int, __buflen: int, /) -> bytes:
        ...

    def getsockopt(self, *args: int) -> int | bytes:
        with self.__lock:
            self._check_not_closed()
            return self.__socket.getsockopt(*args)

    @overload
    def setsockopt(self, __level: int, __optname: int, __value: int | bytes, /) -> None:
        ...

    @overload
    def setsockopt(self, __level: int, __optname: int, __value: None, __optlen: int, /) -> None:
        ...

    def setsockopt(self, *args: Any) -> None:
        with self.__lock:
            self._check_not_closed()
            return self.__socket.setsockopt(*args)

    @final
    def _check_not_closed(self) -> None:
        if self.__closed:
            raise RuntimeError("Closed client")

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
        socket: Socket,
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
        __arg: Socket | tuple[str, int],
        /,
        protocol: DatagramProtocol[_SentPacketT, _ReceivedPacketT],
        **kwargs: Any,
    ) -> None:
        super().__init__()

        endpoint: UDPNetworkEndpoint[_SentPacketT, _ReceivedPacketT]
        if isinstance(__arg, Socket):
            socket = __arg
            endpoint = UDPNetworkEndpoint(protocol, socket=socket, **kwargs)
        elif isinstance(__arg, tuple):
            address = __arg
            endpoint = UDPNetworkEndpoint(protocol, remote_address=address, **kwargs)
        else:
            raise TypeError("Invalid arguments")

        remote_address = endpoint.get_remote_address()
        if remote_address is None:
            raise OSError("No remote address configured")

        self.__endpoint: UDPNetworkEndpoint[_SentPacketT, _ReceivedPacketT] = endpoint
        self.__peer: SocketAddress = remote_address

    @final
    def is_closed(self) -> bool:
        return self.__endpoint.is_closed()

    def close(self) -> None:
        self.__endpoint.close()

    def get_local_address(self) -> SocketAddress:
        return self.__endpoint.get_local_address()

    def get_remote_address(self) -> SocketAddress:
        return self.__peer

    def send_packet(self, packet: _SentPacketT) -> None:
        return self.__endpoint.send_packet(None, packet)

    def send_packets(self, *packets: _SentPacketT) -> None:
        return self.__endpoint.send_packets(None, *packets)

    def recv_packet(self) -> _ReceivedPacketT:
        return self.__endpoint.recv_packet()[0]

    @overload
    def recv_packet_no_block(self, *, timeout: float = ...) -> _ReceivedPacketT:
        ...

    @overload
    def recv_packet_no_block(self, *, default: _T, timeout: float = ...) -> _ReceivedPacketT | _T:
        ...

    def recv_packet_no_block(
        self,
        *,
        default: _T = _NO_DEFAULT,
        timeout: float = 0,
    ) -> _ReceivedPacketT | _T:
        try:
            return self.__endpoint.recv_packet_no_block(timeout=timeout)[0]
        except TimeoutError:
            if default is not _NO_DEFAULT:
                return default
            raise

    def iter_received_packets(self, *, timeout: float = 0) -> Iterator[_ReceivedPacketT]:
        return map(itemgetter(0), self.__endpoint.iter_received_packets(timeout=timeout))

    def fileno(self) -> int:
        return self.__endpoint.fileno()

    def dup(self) -> Socket:
        return self.__endpoint.dup()

    @overload
    def getsockopt(self, __level: int, __optname: int, /) -> int:
        ...

    @overload
    def getsockopt(self, __level: int, __optname: int, __buflen: int, /) -> bytes:
        ...

    def getsockopt(self, *args: int) -> int | bytes:
        return self.__endpoint.getsockopt(*args)

    @overload
    def setsockopt(self, __level: int, __optname: int, __value: int | bytes, /) -> None:
        ...

    @overload
    def setsockopt(self, __level: int, __optname: int, __value: None, __optlen: int, /) -> None:
        ...

    def setsockopt(self, *args: Any) -> None:
        return self.__endpoint.setsockopt(*args)

    @property
    @final
    def default_send_flags(self) -> int:
        return self.__endpoint.default_send_flags

    @property
    @final
    def default_recv_flags(self) -> int:
        return self.__endpoint.default_recv_flags


@contextmanager
def _use_timeout(socket: Socket, timeout: float | None) -> Iterator[None]:
    old_timeout: float | None = socket.gettimeout()
    socket.settimeout(timeout)
    try:
        yield
    finally:
        socket.settimeout(old_timeout)
