# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2022, Francis Clairicia-Rose-Claire-Josephine
#
#
# mypy: no-warn-unused-ignores
"""Network client module"""

from __future__ import annotations

__all__ = ["UDPInvalidPacket", "UDPNetworkClient"]

from collections import deque
from contextlib import contextmanager
from selectors import EVENT_READ
from socket import socket as Socket
from threading import RLock
from typing import Any, Generic, Iterator, Literal, TypeAlias, TypeVar, final, overload

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


class UDPNetworkClient(AbstractNetworkClient, Generic[_SentPacketT, _ReceivedPacketT]):
    __slots__ = (
        "__socket",
        "__owner",
        "__closed",
        "__protocol",
        "__queue",
        "__lock",
        "__default_send_flags",
        "__default_recv_flags",
        "__on_recv_error",
    )

    @overload
    def __init__(
        self,
        /,
        protocol: NetworkProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        family: int = ...,
        source_address: tuple[bytearray | bytes | str, int] | None = ...,
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
        if "socket" in kwargs:
            socket = kwargs.pop("socket")
            if not isinstance(socket, Socket):
                raise TypeError("Invalid arguments")
            give: bool = kwargs.pop("give", False)
            if kwargs:
                raise TypeError("Invalid arguments")
            self.__owner = bool(give)
        else:
            family = AddressFamily(kwargs.pop("family", AF_INET))
            source_address: tuple[bytearray | bytes | str, int] | None = kwargs.pop("source_address", None)
            if kwargs:
                raise TypeError("Invalid arguments")
            socket = Socket(family, SOCK_DGRAM)
            if source_address is None:
                socket.bind(("", 0))
            else:
                socket.bind(source_address)
            self.__owner = True

        if socket.type != SOCK_DGRAM:
            raise ValueError("Invalid socket type")

        self.__closed: bool = False
        self.__socket: Socket = socket
        self.__queue: deque[tuple[bytes, SocketAddress]] = deque()
        self.__lock: RLock = RLock()
        self.__default_send_flags: int = send_flags
        self.__default_recv_flags: int = recv_flags
        self.__on_recv_error: Literal["ignore", "raise"] = on_recv_error

    def close(self) -> None:
        with self.__lock:
            if self.__closed:
                return
            self.__closed = True
            socket: Socket = self.__socket
            del self.__socket
            if not self.__owner:
                return
            socket.close()

    def send_packet(self, address: _Address, packet: _SentPacketT, *, flags: int = 0) -> None:
        flags |= self.__default_send_flags
        self._check_not_closed()
        with self.__lock:
            self.__socket.sendto(self.__protocol.serialize(packet), flags, address)

    def send_packets(self, address: _Address, *packets: _SentPacketT, flags: int = 0) -> None:
        flags |= self.__default_send_flags
        self._check_not_closed()
        if not packets:
            return
        with self.__lock:
            sendto = self.__socket.sendto
            for data in map(self.__protocol.serialize, packets):
                sendto(data, flags, address)

    def recv_packet(
        self,
        *,
        flags: int = 0,
        on_error: Literal["raise", "ignore"] | None = None,
    ) -> tuple[_ReceivedPacketT, SocketAddress]:
        self._check_not_closed()
        with self.__lock:
            while True:
                packet = self.__next_packet(on_error=on_error)
                if packet is not None:
                    return packet
                self.__recv_packets(flags=flags, timeout=None)

    @overload
    def recv_packet_no_block(
        self, *, flags: int = 0, timeout: float = ..., on_error: Literal["raise", "ignore"] | None = ...
    ) -> tuple[_ReceivedPacketT, SocketAddress]:
        ...

    @overload
    def recv_packet_no_block(
        self, *, flags: int = 0, default: _T, timeout: float = ..., on_error: Literal["raise", "ignore"] | None = ...
    ) -> tuple[_ReceivedPacketT, SocketAddress] | _T:
        ...

    def recv_packet_no_block(
        self,
        *,
        flags: int = 0,
        default: Any = _NO_DEFAULT,
        timeout: float = 0,
        on_error: Literal["raise", "ignore"] | None = None,
    ) -> Any:
        self._check_not_closed()
        timeout = float(timeout)
        with self.__lock:
            packet = self.__next_packet(on_error=on_error)
            if packet is not None:
                return packet
            self.__recv_packets(flags=flags, timeout=timeout)
            packet = self.__next_packet(on_error=on_error)
            if packet is not None:
                return packet
            if default is not _NO_DEFAULT:
                return default
            raise TimeoutError("recv_packet() timed out")

    def recv_packets(
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
                    next_packet = get_next_packet(on_error=on_error)
                except UDPInvalidPacket as exc:
                    exc.already_deserialized_packets = packets
                    raise
                if next_packet is None:
                    break
                packets.append(next_packet)
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
                data, sender = socket.recvfrom(65535, flags)
                if not data:
                    continue
                queue.append((data, new_socket_address(sender, socket.family)))

    def __next_packet(self, *, on_error: Literal["raise", "ignore"] | None) -> tuple[_ReceivedPacketT, SocketAddress] | None:
        if on_error is None:
            on_error = self.__on_recv_error
        elif on_error not in ("raise", "ignore"):
            raise ValueError("Invalid on_error value")
        queue: deque[tuple[bytes, SocketAddress]] = self.__queue
        deserialize = self.__protocol.deserialize
        while queue:
            data, sender = queue.popleft()
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


@contextmanager
def _remove_timeout(socket: Socket) -> Iterator[None]:
    timeout: float | None = socket.gettimeout()
    socket.settimeout(None)
    try:
        yield
    finally:
        socket.settimeout(timeout)
