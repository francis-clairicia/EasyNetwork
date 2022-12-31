# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2022, Francis Clairicia-Rose-Claire-Josephine
#
#
# mypy: no-warn-unused-ignores
"""Network client module"""

from __future__ import annotations

__all__ = ["UDPInvalidPacket", "UDPNetworkClient", "UDPNetworkEndpoint"]

from collections import deque
from contextlib import contextmanager
from selectors import EVENT_READ
from socket import socket as Socket
from threading import RLock
from typing import TYPE_CHECKING, Any, Callable, Final, Generic, Iterator, Literal, TypeAlias, TypeVar, final, overload

try:
    from selectors import PollSelector as _Selector  # type: ignore[attr-defined]
except ImportError:
    from selectors import SelectSelector as _Selector  # type: ignore[misc,assignment]

from ..protocol.abc import NetworkProtocol
from ..protocol.exceptions import DeserializeError
from ..tools.socket import AddressFamily, SocketAddress, new_socket_address
from .abc import AbstractNetworkClient

_T = TypeVar("_T")
_ReceivedPacketT = TypeVar("_ReceivedPacketT")
_SentPacketT = TypeVar("_SentPacketT")


_Address: TypeAlias = tuple[str, int] | tuple[str, int, int, int]  # type: ignore[misc]
# False positive, see https://github.com/python/mypy/issues/11098


_NO_DEFAULT: Any = object()


class UDPInvalidPacket(ValueError):
    def __init__(self, sender: SocketAddress, already_deserialized_packets: list[Any] | None = None) -> None:
        super().__init__("Received invalid data to deserialize")
        self.already_deserialized_packets: list[Any] = already_deserialized_packets or []
        self.sender: SocketAddress = sender


class UDPNetworkEndpoint(Generic[_SentPacketT, _ReceivedPacketT]):
    __slots__ = (
        "__socket",
        "__peer",
        "__owner",
        "__closed",
        "__protocol",
        "__queue",
        "__lock",
        "__default_send_flags",
        "__default_recv_flags",
        "__on_recv_error",
    )

    if TYPE_CHECKING:
        __Self = TypeVar("__Self", bound="UDPNetworkEndpoint[Any, Any]")

    MAX_SIZE: Final[int] = 64 * 1024

    @overload
    def __init__(
        self,
        /,
        protocol: NetworkProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        family: int = ...,
        remote_address: tuple[str, int] | None = ...,
        source_address: tuple[str, int] | None = ...,
        send_flags: int = ...,
        recv_flags: int = ...,
        on_recv_error: Literal["ignore", "raise"] = ...,
    ) -> None:
        ...

    @overload
    def __init__(
        self,
        /,
        protocol: NetworkProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        socket: Socket,
        give: bool = ...,
        send_flags: int = ...,
        recv_flags: int = ...,
        on_recv_error: Literal["ignore", "raise"] = ...,
    ) -> None:
        ...

    def __init__(
        self,
        /,
        protocol: NetworkProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        send_flags: int = 0,
        recv_flags: int = 0,
        on_recv_error: Literal["ignore", "raise"] = "raise",
        **kwargs: Any,
    ) -> None:
        send_flags = int(send_flags)
        recv_flags = int(recv_flags)

        if not isinstance(protocol, NetworkProtocol):
            raise TypeError("Invalid argument")

        if on_recv_error not in ("raise", "ignore"):
            raise ValueError("Invalid on_error value")

        super().__init__()

        self.__protocol: NetworkProtocol[_SentPacketT, _ReceivedPacketT] = protocol

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
            try:
                peername = new_socket_address(socket.getpeername(), socket.family)
            except OSError:
                peername = None
        else:
            family = AddressFamily(kwargs.pop("family", AF_INET))
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
                if remote_address is not None:
                    former_timeout = socket.gettimeout()
                    socket.settimeout(0)
                    socket.connect(remote_address)
                    socket.settimeout(former_timeout)
                    peername = new_socket_address(socket.getpeername(), socket.family)
            except BaseException:
                socket.close()
                raise

            self.__owner = True

        if socket.type != SOCK_DGRAM:
            raise ValueError("Invalid socket type")

        self.__peer: SocketAddress | None = peername
        self.__closed: bool = False
        self.__socket: Socket = socket
        self.__queue: deque[tuple[bytes, SocketAddress]] = deque()
        self.__lock: RLock = RLock()
        self.__default_send_flags: int = send_flags
        self.__default_recv_flags: int = recv_flags
        self.__on_recv_error: Literal["ignore", "raise"] = on_recv_error

    def __enter__(self: __Self) -> __Self:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

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
        *,
        timeout: float | None = None,
        flags: int = 0,
    ) -> None:
        address = self._verify_address(address)
        flags |= self.__default_send_flags
        self._check_not_closed()
        socket = self.__socket
        with self.__lock, _use_timeout(socket, timeout):
            if self.__peer:
                socket.send(self.__protocol.serialize(packet), flags)
            else:
                socket.sendto(self.__protocol.serialize(packet), flags, address)

    def send_packets(
        self,
        address: _Address | None,
        *packets: _SentPacketT,
        timeout: float | None = None,
        flags: int = 0,
    ) -> None:
        address = self._verify_address(address)
        flags |= self.__default_send_flags
        self._check_not_closed()
        if not packets:
            return
        socket = self.__socket
        with self.__lock, _use_timeout(socket, timeout):
            send: Callable[[bytes, int], int]
            if self.__peer:
                send = socket.send
            else:
                _sendto = socket.sendto
                send = lambda data, flags: _sendto(data, flags, address)  # type: ignore[arg-type]
            for data in map(self.__protocol.serialize, packets):
                send(data, flags)

    def _verify_address(self, address: _Address | None) -> _Address:
        if remote_addr := self.__peer:
            if address not in (None, remote_addr):
                raise ValueError(f"Invalid address: must be None or {remote_addr}")
            return remote_addr  # type: ignore[return-value]
        if address is None:
            raise ValueError("Invalid address: must not be None")
        return address

    def recv_packet_from_anyone(
        self,
        *,
        flags: int = 0,
        on_error: Literal["raise", "ignore"] | None = None,
    ) -> tuple[_ReceivedPacketT, SocketAddress]:
        self._check_not_closed()
        with self.__lock:
            while True:
                packet_tuple = self.__next_packet(on_error=on_error, only_remote=False)
                if packet_tuple is not None:
                    return packet_tuple
                self.__recv_packets(flags=flags, timeout=None)

    @overload
    def recv_packet_no_block_from_anyone(
        self, *, flags: int = ..., timeout: float = ..., on_error: Literal["raise", "ignore"] | None = ...
    ) -> tuple[_ReceivedPacketT, SocketAddress]:
        ...

    @overload
    def recv_packet_no_block_from_anyone(
        self, *, flags: int = ..., default: _T, timeout: float = ..., on_error: Literal["raise", "ignore"] | None = ...
    ) -> tuple[_ReceivedPacketT, SocketAddress] | _T:
        ...

    def recv_packet_no_block_from_anyone(
        self,
        *,
        flags: int = 0,
        default: _T = _NO_DEFAULT,
        timeout: float = 0,
        on_error: Literal["raise", "ignore"] | None = None,
    ) -> tuple[_ReceivedPacketT, SocketAddress] | _T:
        self._check_not_closed()
        timeout = float(timeout)
        with self.__lock:
            packet_tuple = self.__next_packet(on_error=on_error, only_remote=False)
            if packet_tuple is not None:
                return packet_tuple
            self.__recv_packets(flags=flags, timeout=timeout)
            packet_tuple = self.__next_packet(on_error=on_error, only_remote=False)
            if packet_tuple is not None:
                return packet_tuple
            if default is not _NO_DEFAULT:
                return default
            raise TimeoutError("recv_packet() timed out")

    def recv_packets_from_anyone(
        self,
        *,
        flags: int = 0,
        timeout: float | None = 0,
        on_error: Literal["raise", "ignore"] | None = None,
    ) -> list[tuple[_ReceivedPacketT, SocketAddress]]:
        self._check_not_closed()

        get_next_packet = self.__next_packet

        def generate_packets() -> list[tuple[_ReceivedPacketT, SocketAddress]]:
            packets: list[tuple[_ReceivedPacketT, SocketAddress]] = []
            while True:
                try:
                    next_packet_tuple = get_next_packet(on_error=on_error, only_remote=False)
                except UDPInvalidPacket as exc:
                    exc.already_deserialized_packets = packets
                    raise
                if next_packet_tuple is None:
                    break
                packets.append(next_packet_tuple)
            return packets

        with self.__lock:
            if timeout is not None:
                self.__recv_packets(flags=flags, timeout=timeout)
                return generate_packets()
            while not (packets := generate_packets()):
                self.__recv_packets(flags=flags, timeout=None)
            return packets

    def recv_packet_from_remote(
        self,
        *,
        flags: int = 0,
        on_error: Literal["raise", "ignore"] | None = None,
    ) -> _ReceivedPacketT:
        self._check_not_closed()
        with self.__lock:
            while True:
                packet_tuple = self.__next_packet(on_error=on_error, only_remote=True)
                if packet_tuple is not None:
                    return packet_tuple[0]
                self.__recv_packets(flags=flags, timeout=None)

    @overload
    def recv_packet_no_block_from_remote(
        self, *, flags: int = ..., timeout: float = ..., on_error: Literal["raise", "ignore"] | None = ...
    ) -> _ReceivedPacketT:
        ...

    @overload
    def recv_packet_no_block_from_remote(
        self, *, flags: int = ..., default: _T, timeout: float = ..., on_error: Literal["raise", "ignore"] | None = ...
    ) -> _ReceivedPacketT | _T:
        ...

    def recv_packet_no_block_from_remote(
        self,
        *,
        flags: int = 0,
        default: _T = _NO_DEFAULT,
        timeout: float = 0,
        on_error: Literal["raise", "ignore"] | None = None,
    ) -> _ReceivedPacketT | _T:
        self._check_not_closed()
        timeout = float(timeout)
        with self.__lock:
            packet_tuple = self.__next_packet(on_error=on_error, only_remote=True)
            if packet_tuple is not None:
                return packet_tuple[0]
            self.__recv_packets(flags=flags, timeout=timeout)
            packet_tuple = self.__next_packet(on_error=on_error, only_remote=True)
            if packet_tuple is not None:
                return packet_tuple[0]
            if default is not _NO_DEFAULT:
                return default
            raise TimeoutError("recv_packet() timed out")

    def recv_packets_from_remote(
        self,
        *,
        flags: int = 0,
        timeout: float | None = 0,
        on_error: Literal["raise", "ignore"] | None = None,
    ) -> list[_ReceivedPacketT]:
        self._check_not_closed()

        get_next_packet = self.__next_packet

        def generate_packets() -> list[_ReceivedPacketT]:
            packets: list[_ReceivedPacketT] = []
            while True:
                try:
                    next_packet_tuple = get_next_packet(on_error=on_error, only_remote=True)
                except UDPInvalidPacket as exc:
                    exc.already_deserialized_packets = packets
                    raise
                if next_packet_tuple is None:
                    break
                packets.append(next_packet_tuple[0])
            return packets

        with self.__lock:
            if timeout is not None:
                self.__recv_packets(flags=flags, timeout=timeout)
                return generate_packets()
            while not (packets := generate_packets()):
                self.__recv_packets(flags=flags, timeout=None)
            return packets

    def __recv_packets(self, *, flags: int, timeout: float | None) -> None:
        flags |= self.__default_recv_flags
        if timeout is not None and timeout < 0:
            raise ValueError("Timeout out of range")

        socket: Socket = self.__socket
        queue: deque[tuple[bytes, SocketAddress]] = self.__queue

        if queue:
            timeout = 0
        with _Selector() as selector, _remove_timeout(socket):
            selector.register(socket, EVENT_READ)
            while timeout is None or selector.select(timeout=timeout):
                timeout = 0  # Future select() must exit quickly
                data, sender = socket.recvfrom(self.MAX_SIZE, flags)
                if not data:
                    continue
                queue.append((data, new_socket_address(sender, socket.family)))

    def __next_packet(
        self,
        *,
        on_error: Literal["raise", "ignore"] | None,
        only_remote: bool,
    ) -> tuple[_ReceivedPacketT, SocketAddress] | None:
        if on_error is None:
            on_error = self.__on_recv_error
        elif on_error not in ("raise", "ignore"):
            raise ValueError("Invalid on_error value")
        remote_address: SocketAddress | None
        if only_remote:
            remote_address = self.__peer
            if remote_address is None:
                raise ValueError("No remote address")
        else:
            remote_address = None
        queue: deque[tuple[bytes, SocketAddress]] = self.__queue
        deserialize = self.__protocol.deserialize
        while queue:
            data, sender = queue.popleft()
            if remote_address is not None and sender != remote_address:
                continue
            try:
                packet = deserialize(data)
            except DeserializeError as exc:
                if on_error == "raise":
                    raise UDPInvalidPacket(sender) from exc
                continue
            return packet, sender
        return None

    def getsockname(self) -> SocketAddress:
        self._check_not_closed()
        return new_socket_address(self.__socket.getsockname(), self.__socket.family)

    def getpeername(self) -> SocketAddress | None:
        self._check_not_closed()
        return self.__peer

    def fileno(self) -> int:
        if self.__closed:
            return -1
        return self.__socket.fileno()

    def dup(self) -> Socket:
        self._check_not_closed()
        socket: Socket = self.__socket
        return socket.dup()

    def detach(self) -> Socket:
        self._check_not_closed()
        socket: Socket = self.__socket
        fd: int = socket.detach()
        if fd < 0:
            raise OSError("Closed socket")
        socket = Socket(socket.family, socket.type, socket.proto, fileno=fd)
        try:
            self.__owner = False
            self.close()
        except BaseException:
            socket.close()
            raise
        return socket

    @overload
    def getsockopt(self, __level: int, __optname: int, /) -> int:
        ...

    @overload
    def getsockopt(self, __level: int, __optname: int, __buflen: int, /) -> bytes:
        ...

    def getsockopt(self, *args: int) -> int | bytes:
        self._check_not_closed()
        return self.__socket.getsockopt(*args)

    @overload
    def setsockopt(self, __level: int, __optname: int, __value: int | bytes, /) -> None:
        ...

    @overload
    def setsockopt(self, __level: int, __optname: int, __value: None, __optlen: int, /) -> None:
        ...

    def setsockopt(self, *args: Any) -> None:
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

    @property
    @final
    def closed(self) -> bool:
        return self.__closed


class UDPNetworkClient(AbstractNetworkClient[_SentPacketT, _ReceivedPacketT], Generic[_SentPacketT, _ReceivedPacketT]):
    __slots__ = ("__endpoint", "__peer")

    @overload
    def __init__(
        self,
        address: tuple[str, int],
        /,
        protocol: NetworkProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        family: int = ...,
        source_address: tuple[str, int] | None = ...,
        send_flags: int = ...,
        recv_flags: int = ...,
        on_recv_error: Literal["ignore", "raise"] = ...,
    ) -> None:
        ...

    @overload
    def __init__(
        self,
        socket: Socket,
        /,
        protocol: NetworkProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        give: bool = ...,
        send_flags: int = ...,
        recv_flags: int = ...,
        on_recv_error: Literal["ignore", "raise"] = ...,
    ) -> None:
        ...

    def __init__(
        self,
        __arg: Socket | tuple[str, int],
        /,
        protocol: NetworkProtocol[_SentPacketT, _ReceivedPacketT],
        **kwargs: Any,
    ) -> None:
        endpoint: UDPNetworkEndpoint[_SentPacketT, _ReceivedPacketT]
        if isinstance(__arg, Socket):
            socket = __arg
            endpoint = UDPNetworkEndpoint(protocol, socket=socket, **kwargs)
        elif isinstance(__arg, tuple):
            address = __arg
            endpoint = UDPNetworkEndpoint(protocol, remote_address=address, **kwargs)
        else:
            raise TypeError("Invalid arguments")

        remote_address = endpoint.getpeername()
        if remote_address is None:
            raise OSError("No remote address configured")

        super().__init__()

        self.__endpoint: UDPNetworkEndpoint[_SentPacketT, _ReceivedPacketT] = endpoint
        self.__peer: SocketAddress = remote_address

    def close(self) -> None:
        self.__endpoint.close()

    def getsockname(self) -> SocketAddress:
        return self.__endpoint.getsockname()

    def getpeername(self) -> SocketAddress:
        return self.__peer

    def send_packet(self, packet: _SentPacketT, *, timeout: float | None = None, flags: int = 0) -> None:
        return self.__endpoint.send_packet(None, packet, timeout=timeout, flags=flags)

    def send_packets(self, *packets: _SentPacketT, timeout: float | None = None, flags: int = 0) -> None:
        return self.__endpoint.send_packet(None, *packets, timeout=timeout, flags=flags)

    def recv_packet(self, *, flags: int = 0, on_error: Literal["raise", "ignore"] | None = None) -> _ReceivedPacketT:
        return self.__endpoint.recv_packet_from_remote(flags=flags, on_error=on_error)

    @overload
    def recv_packet_no_block(
        self, *, timeout: float = ..., flags: int = ..., on_error: Literal["raise", "ignore"] | None = ...
    ) -> _ReceivedPacketT:
        ...

    @overload
    def recv_packet_no_block(
        self, *, default: _T, timeout: float = ..., flags: int = ..., on_error: Literal["raise", "ignore"] | None = ...
    ) -> _ReceivedPacketT | _T:
        ...

    def recv_packet_no_block(
        self,
        *,
        default: _T = _NO_DEFAULT,
        timeout: float = 0,
        flags: int = 0,
        on_error: Literal["raise", "ignore"] | None = None,
    ) -> _ReceivedPacketT | _T:
        return self.__endpoint.recv_packet_no_block_from_remote(default=default, timeout=timeout, flags=flags, on_error=on_error)

    def recv_packets(
        self,
        *,
        timeout: float | None = 0,
        flags: int = 0,
        on_error: Literal["raise", "ignore"] | None = None,
    ) -> list[_ReceivedPacketT]:
        return self.__endpoint.recv_packets_from_remote(flags=flags, timeout=timeout, on_error=on_error)

    def fileno(self) -> int:
        return self.__endpoint.fileno()

    def dup(self) -> Socket:
        return self.__endpoint.dup()

    def detach(self) -> Socket:
        return self.__endpoint.detach()

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

    @property
    @final
    def closed(self) -> bool:
        return self.__endpoint.closed


@contextmanager
def _remove_timeout(socket: Socket) -> Iterator[None]:
    timeout: float | None = socket.gettimeout()
    socket.settimeout(None)
    try:
        yield
    finally:
        socket.settimeout(timeout)


@contextmanager
def _use_timeout(socket: Socket, timeout: float | None) -> Iterator[None]:
    old_timeout: float | None = socket.gettimeout()
    socket.settimeout(timeout)
    try:
        yield
    finally:
        socket.settimeout(old_timeout)
