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

from ..protocol import StreamProtocol, StreamProtocolParseError
from ..tools.socket import SocketAddress, SocketProxy, new_socket_address
from ..tools.stream import StreamDataConsumer, StreamDataProducer
from .abc import AbstractNetworkClient

_T = TypeVar("_T")
_ReceivedPacketT = TypeVar("_ReceivedPacketT")
_SentPacketT = TypeVar("_SentPacketT")


_NO_DEFAULT: Any = object()


class TCPNetworkClient(AbstractNetworkClient[_SentPacketT, _ReceivedPacketT], Generic[_SentPacketT, _ReceivedPacketT]):
    __slots__ = (
        "__socket",
        "__socket_proxy",
        "__owner",
        "__closed",
        "__lock",
        "__producer",
        "__consumer",
        "__addr",
        "__peer",
        "__eof_reached",
        "__default_send_flags",
        "__default_recv_flags",
    )

    max_size: int = 256 * 1024  # Buffer size passed to recv().

    @overload
    def __init__(
        self,
        address: tuple[str, int],
        /,
        protocol: StreamProtocol[_SentPacketT, _ReceivedPacketT],
        *,
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
        protocol: StreamProtocol[_SentPacketT, _ReceivedPacketT],
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
        protocol: StreamProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        send_flags: int = 0,
        recv_flags: int = 0,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        self.__producer: StreamDataProducer[_SentPacketT] = StreamDataProducer(protocol)
        self.__consumer: StreamDataConsumer[_ReceivedPacketT] = StreamDataConsumer(protocol)

        send_flags = int(send_flags)
        recv_flags = int(recv_flags)
        socket: Socket

        self.__owner: bool
        if isinstance(__arg, Socket):
            give: bool = kwargs.pop("give", False)
            if kwargs:
                raise TypeError("Invalid arguments")
            socket = __arg
            self.__owner = bool(give)
        elif isinstance(__arg, tuple):
            from socket import create_connection

            address: tuple[str, int] = __arg
            socket = create_connection(address, **kwargs)
            self.__owner = True
        else:
            raise TypeError("Invalid arguments")

        from socket import SOCK_STREAM

        if socket.type != SOCK_STREAM:
            raise ValueError("Invalid socket type")

        socket.settimeout(None)

        self.__addr: SocketAddress = new_socket_address(socket.getsockname(), socket.family)
        self.__peer: SocketAddress = new_socket_address(socket.getpeername(), socket.family)
        self.__closed: bool = False
        self.__socket: Socket = socket
        self.__socket_proxy: SocketProxy | None = SocketProxy(socket)
        self.__lock: RLock = RLock()
        self.__eof_reached: bool = False
        self.__default_send_flags: int = send_flags
        self.__default_recv_flags: int = recv_flags

    def __repr__(self) -> str:
        try:
            socket = self.__socket
        except AttributeError:
            return f"<{type(self).__name__} closed>"
        return f"<{type(self).__name__} socket={socket!r}"

    @final
    def is_closed(self) -> bool:
        return self.__closed

    def close(self) -> None:
        with self.__lock:
            if self.__closed:
                return
            self.__eof_reached = True
            self.__closed = True
            socket: Socket = self.__socket
            del self.__socket
            self.__socket_proxy = None
            if not self.__owner:
                return
            try:
                from socket import SHUT_WR

                socket.shutdown(SHUT_WR)
            except OSError:
                pass
            finally:
                socket.close()

    def send_packet(self, packet: _SentPacketT) -> None:
        with self.__lock:
            self._check_not_closed()
            self.__producer.queue(packet)
            self.__write_on_socket()

    def send_packets(self, *packets: _SentPacketT) -> None:
        if not packets:
            return
        with self.__lock:
            self._check_not_closed()
            self.__producer.queue(*packets)
            self.__write_on_socket()

    def __write_on_socket(self) -> None:
        flags = self.__default_send_flags
        socket: Socket = self.__socket
        if self.__eof_reached:
            import errno
            import os

            raise OSError(errno.EPIPE, os.strerror(errno.EPIPE))
        with _use_timeout(socket, None):
            socket.sendall(b"".join(list(self.__producer)), flags)

    def recv_packet(self) -> _ReceivedPacketT:
        with self.__lock:
            self._check_not_closed()
            consumer = self.__consumer
            read_socket = self.__read_socket
            next_packet = self.__next_packet
            while True:
                try:
                    return next_packet(consumer)
                except StopIteration:
                    pass
                while not read_socket(timeout=None):
                    continue

    @overload
    def recv_packet_no_block(self, *, timeout: float = ...) -> _ReceivedPacketT:
        ...

    @overload
    def recv_packet_no_block(self, *, default: _T, timeout: float = ...) -> _ReceivedPacketT | _T:
        ...

    def recv_packet_no_block(self, *, default: Any = _NO_DEFAULT, timeout: float = 0) -> Any:
        timeout = float(timeout)
        next_packet = self.__next_packet
        with self.__lock:
            self._check_not_closed()
            consumer = self.__consumer
            try:
                return next_packet(consumer)
            except StopIteration:
                pass
            read_socket = self.__read_socket
            while read_socket(timeout=timeout):
                try:
                    return next_packet(consumer)
                except StopIteration:
                    pass
            if default is not _NO_DEFAULT:
                return default
            raise TimeoutError("recv_packet() timed out")

    def iter_received_packets(self, *, timeout: float = 0) -> Iterator[_ReceivedPacketT]:
        timeout = float(timeout)
        consumer = self.__consumer
        read_socket = self.__read_socket
        check_not_closed = self._check_not_closed
        next_packet = self.__next_packet_or_default
        lock = self.__lock
        null: Any = object()
        while True:
            with lock:
                check_not_closed()
                while (packet := next_packet(consumer, null)) is null:
                    if not read_socket(timeout=timeout):
                        return
                    continue
            yield packet  # yield out of lock scope

    def __read_socket(self, *, timeout: float | None) -> bool:
        if self.__eof_reached:
            raise EOFError("Closed connection")
        flags = self.__default_recv_flags
        socket: Socket = self.__socket
        with _use_timeout(socket, timeout):
            try:
                chunk: bytes = socket.recv(self.max_size, flags)
            except (TimeoutError, BlockingIOError, InterruptedError):
                return False
            if not chunk:
                self.__eof_reached = True
                raise EOFError("Closed connection")
            self.__consumer.feed(chunk)
            return True

    @staticmethod
    def __next_packet(consumer: StreamDataConsumer[_ReceivedPacketT]) -> _ReceivedPacketT:
        try:
            return next(consumer)
        except (StopIteration, StreamProtocolParseError):
            raise
        except Exception as exc:
            raise RuntimeError(str(exc)) from exc

    @staticmethod
    def __next_packet_or_default(consumer: StreamDataConsumer[_ReceivedPacketT], default: _T) -> _ReceivedPacketT | _T:
        try:
            return next(consumer, default)
        except StreamProtocolParseError:
            raise
        except Exception as exc:
            raise RuntimeError(str(exc)) from exc

    def get_local_address(self) -> SocketAddress:
        with self.__lock:
            self._check_not_closed()
            return self.__addr

    def get_remote_address(self) -> SocketAddress:
        with self.__lock:
            self._check_not_closed()
            return self.__peer

    def is_connected(self) -> bool:
        with self.__lock:
            if self.__closed or self.__eof_reached:
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

    @final
    def _check_not_closed(self) -> None:
        if self.__closed:
            raise RuntimeError("Closed client")

    @property
    @final
    def socket(self) -> SocketProxy:
        with self.__lock:
            socket = self.__socket_proxy
            if socket is None:
                raise RuntimeError("Closed client")
            return socket

    @property
    @final
    def default_send_flags(self) -> int:
        return self.__default_send_flags

    @property
    @final
    def default_recv_flags(self) -> int:
        return self.__default_recv_flags


@contextmanager
def _use_timeout(socket: Socket, timeout: float | None) -> Iterator[None]:
    old_timeout: float | None = socket.gettimeout()
    socket.settimeout(timeout)
    try:
        yield
    finally:
        socket.settimeout(old_timeout)
