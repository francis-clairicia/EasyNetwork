# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2022, Francis Clairicia-Rose-Claire-Josephine
#
#
# mypy: no-warn-unused-ignores
"""Network client module"""

from __future__ import annotations

__all__ = ["TCPInvalidPacket", "TCPNetworkClient"]

from contextlib import contextmanager
from selectors import EVENT_READ
from socket import socket as Socket
from threading import RLock
from typing import Any, Generic, Iterator, Literal, TypeVar, final, overload

try:
    from selectors import PollSelector as _Selector  # type: ignore[attr-defined]
except ImportError:
    from selectors import SelectSelector as _Selector  # type: ignore[misc,assignment]

from ..protocol.exceptions import DeserializeError
from ..protocol.stream.abc import StreamNetworkProtocol
from ..tools.socket import SHUT_WR, SocketAddress, create_connection, guess_best_buffer_size, new_socket_address
from ..tools.stream import StreamNetworkDataConsumer, StreamNetworkDataProducerIterator
from .abc import AbstractNetworkClient

_T = TypeVar("_T")
_ReceivedPacketT = TypeVar("_ReceivedPacketT")
_SentPacketT = TypeVar("_SentPacketT")


_NO_DEFAULT: Any = object()


class TCPInvalidPacket(ValueError):
    def __init__(self, already_deserialized_packets: list[Any] | None = None) -> None:
        super().__init__("Received invalid data to deserialize")
        self.already_deserialized_packets: list[Any] = already_deserialized_packets or []


class TCPNetworkClient(AbstractNetworkClient, Generic[_SentPacketT, _ReceivedPacketT]):
    __slots__ = (
        "__socket",
        "__owner",
        "__closed",
        "__lock",
        "__chunk_size",
        "__producer",
        "__consumer",
        "__peer",
        "__default_send_flags",
        "__default_recv_flags",
        "__buffered_write",
    )

    @overload
    def __init__(
        self,
        address: tuple[str, int],
        /,
        protocol: StreamNetworkProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        timeout: float | None = ...,
        family: int | None = ...,
        source_address: tuple[bytearray | bytes | str, int] | None = ...,
        send_flags: int = ...,
        recv_flags: int = ...,
        on_recv_error: Literal["ignore", "raise"] = ...,
        buffered_write: bool = ...,
    ) -> None:
        ...

    @overload
    def __init__(
        self,
        socket: Socket,
        /,
        protocol: StreamNetworkProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        give: bool = ...,
        send_flags: int = ...,
        recv_flags: int = ...,
        on_recv_error: Literal["ignore", "raise"] = ...,
        buffered_write: bool = ...,
    ) -> None:
        ...

    def __init__(
        self,
        __arg: Socket | tuple[str, int],
        /,
        protocol: StreamNetworkProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        send_flags: int = 0,
        recv_flags: int = 0,
        on_recv_error: Literal["ignore", "raise"] = "raise",
        buffered_write: bool = False,
        **kwargs: Any,
    ) -> None:
        if not isinstance(protocol, StreamNetworkProtocol):
            raise TypeError("Invalid argument")
        send_flags = int(send_flags)
        recv_flags = int(recv_flags)
        socket: Socket

        super().__init__()

        self.__owner: bool
        if isinstance(__arg, Socket):
            give: bool = kwargs.pop("give", False)
            if kwargs:
                raise TypeError("Invalid arguments")
            socket = __arg
            self.__owner = bool(give)
        elif isinstance(__arg, tuple):
            address: tuple[str, int] = __arg
            socket = create_connection(address, **kwargs)
            self.__owner = True
        else:
            raise TypeError("Invalid arguments")

        from socket import SOCK_STREAM

        if socket.type != SOCK_STREAM:
            raise ValueError("Invalid socket type")

        self.__peer: tuple[Any, ...] = socket.getpeername()
        self.__closed: bool = False
        self.__socket: Socket = socket
        self.__lock: RLock = RLock()
        self.__chunk_size: int = guess_best_buffer_size(socket)
        self.__producer: StreamNetworkDataProducerIterator[_SentPacketT] = StreamNetworkDataProducerIterator(protocol)
        self.__consumer: StreamNetworkDataConsumer[_ReceivedPacketT] = StreamNetworkDataConsumer(protocol, on_error=on_recv_error)
        self.__default_send_flags: int = send_flags
        self.__default_recv_flags: int = recv_flags
        self.__buffered_write: bool = bool(buffered_write)

    def close(self) -> None:
        with self.__lock:
            if self.__closed:
                return
            self.__closed = True
            socket: Socket = self.__socket
            del self.__socket
            if not self.__owner:
                return
            try:
                socket.shutdown(SHUT_WR)
            except OSError:
                pass
            finally:
                socket.close()

    def send_packet(self, packet: _SentPacketT, *, timeout: float | None = None, flags: int = 0) -> None:
        self._check_not_closed()
        with self.__lock:
            self.__producer.queue(packet)
            self.__write_on_socket(timeout=timeout, flags=flags)

    def send_packets(self, *packets: _SentPacketT, timeout: float | None = None, flags: int = 0) -> None:
        self._check_not_closed()
        if not packets:
            return
        with self.__lock:
            self.__producer.queue(*packets)
            self.__write_on_socket(timeout=timeout, flags=flags)

    def __write_on_socket(self, *, timeout: float | None, flags: int) -> None:
        if timeout is not None:
            if timeout < 0:
                raise ValueError("Timeout out of range")
            if timeout == 0:
                raise ValueError("non-blocking sockets are not supported")

        flags |= self.__default_send_flags
        socket: Socket = self.__socket
        with _use_timeout(socket, timeout):
            if self.__buffered_write:
                with socket.makefile("wb", buffering=1) as socket_io:
                    for chunk in self.__producer:
                        socket_io.write(chunk)
            else:
                for chunk in self.__producer:
                    socket.sendall(chunk, flags)

    def recv_packet(self, *, flags: int = 0, on_error: Literal["raise", "ignore"] | None = None) -> _ReceivedPacketT:
        self._check_not_closed()
        with self.__lock:
            while True:
                try:
                    return self.__consumer.next(on_error=on_error)
                except DeserializeError as exc:
                    raise TCPInvalidPacket from exc
                except StopIteration:
                    pass
                self.__read_socket(timeout=None, flags=flags)

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
        default: Any = _NO_DEFAULT,
        timeout: float = 0,
        flags: int = 0,
        on_error: Literal["raise", "ignore"] | None = None,
    ) -> Any:
        timeout = float(timeout)
        self._check_not_closed()
        with self.__lock:
            try:
                return self.__consumer.next(on_error=on_error)
            except DeserializeError as exc:
                raise TCPInvalidPacket from exc
            except StopIteration:
                pass
            self.__read_socket(timeout=timeout, flags=flags)
            try:
                return self.__consumer.next(on_error=on_error)
            except DeserializeError as exc:
                raise TCPInvalidPacket from exc
            except StopIteration:
                pass
            if default is not _NO_DEFAULT:
                return default
            raise TimeoutError("recv_packet() timed out")

    def recv_packets(
        self,
        *,
        timeout: float | None = 0,
        flags: int = 0,
        on_error: Literal["raise", "ignore"] | None = None,
    ) -> list[_ReceivedPacketT]:
        self._check_not_closed()

        consumer: StreamNetworkDataConsumer[_ReceivedPacketT] = self.__consumer

        def generate_packets() -> list[_ReceivedPacketT]:
            packets: list[_ReceivedPacketT] = []
            while True:
                try:
                    next_packet = consumer.next(on_error=on_error)
                except DeserializeError as exc:
                    raise TCPInvalidPacket(already_deserialized_packets=packets) from exc
                except StopIteration:
                    break
                packets.append(next_packet)
            return packets

        with self.__lock:
            if timeout is not None:
                self.__read_socket(timeout=timeout, flags=flags)
                return generate_packets()
            while not (packets := generate_packets()):
                self.__read_socket(timeout=None, flags=flags)
            return packets

    def __read_socket(self, *, timeout: float | None, flags: int) -> None:
        flags |= self.__default_recv_flags
        if timeout is not None and timeout < 0:
            raise ValueError("Timeout out of range")

        socket: Socket = self.__socket
        socket_recv = socket.recv
        chunk_size: int = self.__chunk_size
        consumer = self.__consumer
        consumer_feed = consumer.feed
        if consumer.get_buffer():
            timeout = 0
        with _Selector() as selector, _remove_timeout(socket):
            selector.register(socket, EVENT_READ)
            select = selector.select
            while timeout is None or select(timeout=timeout):
                timeout = 0  # Future select() must exit quickly
                chunk: bytes = socket_recv(chunk_size, flags)
                if not chunk:
                    if consumer.get_buffer():
                        # consumer.feed() has been called
                        # The next read_socket() will raise an EOFError
                        return
                    raise EOFError("Closed connection")
                consumer_feed(chunk)

    def getsockname(self) -> SocketAddress:
        self._check_not_closed()
        return new_socket_address(self.__socket.getsockname(), self.__socket.family)

    def getpeername(self) -> SocketAddress | None:
        self._check_not_closed()
        try:
            return new_socket_address(self.__socket.getpeername(), self.__socket.family)
        except OSError:
            return None

    def is_connected(self) -> bool:
        if self.__closed:
            return False
        try:
            self.__socket.getpeername()
        except OSError:
            return False
        return True

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

    def reconnect(self, timeout: float | None = None) -> None:
        self._check_not_closed()
        socket: Socket = self.__socket
        try:
            socket.getpeername()
        except OSError:
            pass
        else:
            return
        address: tuple[Any, ...] = self.__peer
        former_timeout = socket.gettimeout()
        socket.settimeout(timeout)
        try:
            socket.connect(address)
        finally:
            socket.settimeout(former_timeout)

    def try_reconnect(self, timeout: float | None = None) -> bool:
        try:
            self.reconnect(timeout=timeout)
        except OSError:
            return False
        return True

    @final
    def _get_buffer(self) -> bytes:
        return self.__consumer.get_unconsumed_data()

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


@contextmanager
def _use_timeout(socket: Socket, timeout: float | None) -> Iterator[None]:
    old_timeout: float | None = socket.gettimeout()
    socket.settimeout(timeout)
    try:
        yield
    finally:
        socket.settimeout(old_timeout)
