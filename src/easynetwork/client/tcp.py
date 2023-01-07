# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Network client module"""

from __future__ import annotations

__all__ = ["TCPNetworkClient"]

from contextlib import contextmanager
from socket import socket as Socket
from threading import RLock
from typing import Any, Generic, Iterator, TypeVar, final, overload

from ..serializers.stream.abc import IncrementalPacketSerializer
from ..tools.socket import DEFAULT_TIMEOUT, SHUT_WR, SocketAddress, create_connection, guess_best_buffer_size, new_socket_address
from ..tools.stream import StreamNetworkDataConsumer, StreamNetworkDataProducerIterator
from .abc import AbstractNetworkClient

_T = TypeVar("_T")
_ReceivedPacketT = TypeVar("_ReceivedPacketT")
_SentPacketT = TypeVar("_SentPacketT")


_NO_DEFAULT: Any = object()


class TCPNetworkClient(AbstractNetworkClient[_SentPacketT, _ReceivedPacketT], Generic[_SentPacketT, _ReceivedPacketT]):
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
        serializer: IncrementalPacketSerializer[_SentPacketT, _ReceivedPacketT],
        *,
        timeout: float | None = ...,
        source_address: tuple[str, int] | None = ...,
        send_flags: int = ...,
        recv_flags: int = ...,
        buffered_write: bool = ...,
    ) -> None:
        ...

    @overload
    def __init__(
        self,
        socket: Socket,
        /,
        serializer: IncrementalPacketSerializer[_SentPacketT, _ReceivedPacketT],
        *,
        give: bool = ...,
        send_flags: int = ...,
        recv_flags: int = ...,
        buffered_write: bool = ...,
    ) -> None:
        ...

    def __init__(
        self,
        __arg: Socket | tuple[str, int],
        /,
        serializer: IncrementalPacketSerializer[_SentPacketT, _ReceivedPacketT],
        *,
        send_flags: int = 0,
        recv_flags: int = 0,
        buffered_write: bool = False,
        **kwargs: Any,
    ) -> None:
        if not isinstance(serializer, IncrementalPacketSerializer):
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

        self.__peer: SocketAddress = new_socket_address(socket.getpeername(), socket.family)
        self.__closed: bool = False
        self.__socket: Socket = socket
        self.__lock: RLock = RLock()
        self.__chunk_size: int = guess_best_buffer_size(socket)
        self.__producer: StreamNetworkDataProducerIterator[_SentPacketT] = StreamNetworkDataProducerIterator(serializer)
        self.__consumer: StreamNetworkDataConsumer[_ReceivedPacketT] = StreamNetworkDataConsumer(serializer, on_error="ignore")
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

    def send_packet(self, packet: _SentPacketT, *, timeout: float | None = DEFAULT_TIMEOUT, flags: int = 0) -> None:
        with self.__lock:
            self._check_not_closed()
            self.__producer.queue(packet)
            self.__write_on_socket(timeout=timeout, flags=flags)

    def send_packets(self, *packets: _SentPacketT, timeout: float | None = DEFAULT_TIMEOUT, flags: int = 0) -> None:
        if not packets:
            return
        with self.__lock:
            self._check_not_closed()
            self.__producer.queue(*packets)
            self.__write_on_socket(timeout=timeout, flags=flags)

    def __write_on_socket(self, *, timeout: float | None, flags: int) -> None:
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

    def recv_packet(self, *, flags: int = 0) -> _ReceivedPacketT:
        with self.__lock:
            self._check_not_closed()
            next_packet = self.__consumer.next
            read_socket = self.__read_socket
            while True:
                try:
                    return next_packet()
                except EOFError:
                    pass
                while not read_socket(timeout=None, flags=flags):
                    continue

    @overload
    def recv_packet_no_block(
        self,
        *,
        timeout: float = ...,
        flags: int = ...,
    ) -> _ReceivedPacketT:
        ...

    @overload
    def recv_packet_no_block(self, *, default: _T, timeout: float = ..., flags: int = ...) -> _ReceivedPacketT | _T:
        ...

    def recv_packet_no_block(self, *, default: Any = _NO_DEFAULT, timeout: float = 0, flags: int = 0) -> Any:
        timeout = float(timeout)
        with self.__lock:
            self._check_not_closed()
            next_packet = self.__consumer.next
            try:
                return next_packet()
            except EOFError:
                pass
            if self.__read_socket(timeout=timeout, flags=flags):
                try:
                    return next_packet()
                except EOFError:
                    pass
            if default is not _NO_DEFAULT:
                return default
            raise TimeoutError("recv_packet() timed out")

    def iter_received_packets(self, *, timeout: float = 0, flags: int = 0) -> Iterator[_ReceivedPacketT]:
        timeout = float(timeout)
        next_packet = self.__consumer.next
        read_socket = self.__read_socket
        check_not_closed = self._check_not_closed
        lock = self.__lock
        while True:
            with lock:
                check_not_closed()
                try:
                    packet = next_packet()
                except EOFError:
                    if not read_socket(timeout=timeout, flags=flags):
                        return
                    continue
            yield packet  # yield out of lock scope

    def recv_all_packets(self, *, timeout: float = 0, flags: int = 0) -> list[_ReceivedPacketT]:
        with self.__lock:
            return list(self.iter_received_packets(timeout=timeout, flags=flags))

    def __read_socket(self, *, timeout: float | None, flags: int) -> bool:
        flags |= self.__default_recv_flags
        socket: Socket = self.__socket
        with _use_timeout(socket, timeout):
            try:
                chunk: bytes = socket.recv(self.__chunk_size, flags)
            except (TimeoutError, BlockingIOError, InterruptedError):
                return False
            if not chunk:
                raise EOFError("Closed connection")
            self.__consumer.feed(chunk)
            return True

    def get_local_address(self) -> SocketAddress:
        with self.__lock:
            self._check_not_closed()
            return new_socket_address(self.__socket.getsockname(), self.__socket.family)

    def get_remote_address(self) -> SocketAddress:
        with self.__lock:
            self._check_not_closed()
            return self.__peer

    def get_timeout(self) -> float | None:
        with self.__lock:
            self._check_not_closed()
            return self.__socket.gettimeout()

    def set_timeout(self, timeout: float | None) -> None:
        if timeout is DEFAULT_TIMEOUT:
            from socket import getdefaulttimeout

            timeout = getdefaulttimeout()
        with self.__lock:
            self._check_not_closed()
            self.__socket.settimeout(timeout)

    def is_connected(self) -> bool:
        with self.__lock:
            if self.__closed:
                return False
            try:
                self.__socket.getpeername()
            except OSError:
                return False
            return True

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

    def detach(self) -> Socket:
        with self.__lock:
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

    def reconnect(self, timeout: float | None = None) -> None:
        with self.__lock:
            self._check_not_closed()
            socket: Socket = self.__socket
            try:
                socket.getpeername()
            except OSError:
                pass
            else:
                return
            address: tuple[Any, ...] = self.__peer.for_connection()
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
def _use_timeout(socket: Socket, timeout: float | None) -> Iterator[None]:
    if timeout is DEFAULT_TIMEOUT:
        yield
        return
    old_timeout: float | None = socket.gettimeout()
    socket.settimeout(timeout)
    try:
        yield
    finally:
        socket.settimeout(old_timeout)
