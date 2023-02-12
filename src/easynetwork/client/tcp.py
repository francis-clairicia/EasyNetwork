# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Network client module"""

from __future__ import annotations

__all__ = ["TCPNetworkClient"]

import socket as _socket
from contextlib import contextmanager
from threading import RLock
from typing import Any, Generic, Iterator, TypeVar, final, overload

from ..protocol import StreamProtocol, StreamProtocolParseError
from ..tools.socket import MAX_STREAM_BUFSIZE, SocketAddress, SocketProxy, new_socket_address
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
        "__socket_sendall",
        "__socket_recv",
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

    max_size: int = MAX_STREAM_BUFSIZE  # Buffer size passed to recv().

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
        socket: _socket.socket,
        /,
        protocol: StreamProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        give: bool,
        send_flags: int = ...,
        recv_flags: int = ...,
    ) -> None:
        ...

    def __init__(
        self,
        __arg: _socket.socket | tuple[str, int],
        /,
        protocol: StreamProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        send_flags: int = 0,
        recv_flags: int = 0,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        self.__lock: RLock = RLock()
        self.__closed: bool = True  # If any exception occurs, the client will already be in a closed state
        self.__producer: StreamDataProducer[_SentPacketT] = StreamDataProducer(protocol)
        self.__consumer: StreamDataConsumer[_ReceivedPacketT] = StreamDataConsumer(protocol)

        socket: _socket.socket
        self.__owner: bool
        if isinstance(__arg, _socket.socket):
            try:
                give: bool = kwargs.pop("give")
            except KeyError:
                raise TypeError("Missing keyword argument 'give'") from None
            if kwargs:
                raise TypeError("Invalid arguments")
            socket = __arg
            self.__owner = bool(give)
        elif isinstance(__arg, tuple):
            address: tuple[str, int] = __arg
            socket = _socket.create_connection(address, **kwargs)
            self.__owner = True
        else:
            raise TypeError("Invalid arguments")

        try:
            if socket.type != _socket.SOCK_STREAM:
                raise ValueError("Invalid socket type")

            self.__addr: SocketAddress = new_socket_address(socket.getsockname(), socket.family)
            self.__peer: SocketAddress = new_socket_address(socket.getpeername(), socket.family)
            self.__socket_proxy = SocketProxy(socket)
            self.__eof_reached: bool = False
            self.__default_send_flags: int = send_flags
            self.__default_recv_flags: int = recv_flags
        except BaseException:
            if self.__owner:
                socket.close()
            raise

        self.__socket: _socket.socket = socket
        self.__socket_sendall = socket.sendall
        self.__socket_recv = socket.recv
        self.__closed = False  # There was no errors

    def __repr__(self) -> str:
        try:
            socket = self.__socket
        except AttributeError:
            return f"<{type(self).__name__} closed>"
        return f"<{type(self).__name__} socket={socket!r}"

    @final
    def is_closed(self) -> bool:
        return self.__closed

    def close(self, *, shutdown: int | None = -1) -> None:
        if shutdown is not None and shutdown == -1:
            shutdown = _socket.SHUT_WR
        with self.__lock:
            if self.__closed:
                return
            self.__eof_reached = True
            self.__closed = True
            socket: _socket.socket = self.__socket
            del self.__socket
            if not self.__owner:
                return
            try:
                if shutdown is not None:
                    socket.shutdown(shutdown)
            except OSError:
                pass
            finally:
                socket.close()

    def send_packet(self, packet: _SentPacketT) -> None:
        with self.__lock:
            self._check_not_closed()
            if self.__eof_reached:
                import errno
                import os

                raise OSError(errno.EPIPE, os.strerror(errno.EPIPE))
            with _use_timeout(self.__socket, None):
                self.__producer.queue(packet)
                self.__socket_sendall(b"".join(list(self.__producer)), self.__default_send_flags)

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
                read_socket(timeout=None)

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

    def iter_received_packets(self, *, timeout: float | None = 0) -> Iterator[_ReceivedPacketT]:
        consumer = self.__consumer
        read_socket = self.__read_socket
        check_not_closed = self._check_not_closed
        next_packet_or_default = self.__next_packet_or_default
        lock = self.__lock
        null: Any = _NO_DEFAULT

        while True:
            with lock:
                check_not_closed()
                while (packet := next_packet_or_default(consumer, null)) is null:
                    try:
                        if not read_socket(timeout=timeout):
                            return
                    except (OSError, EOFError):
                        return
            yield packet  # yield out of lock scope

    def __read_socket(self, *, timeout: float | None) -> bool:
        if self.__eof_reached:
            raise EOFError("Closed connection")
        with _use_timeout(self.__socket, timeout):
            try:
                chunk: bytes = self.__socket_recv(self.max_size, self.__default_recv_flags)
            except (TimeoutError, BlockingIOError) as exc:
                if timeout is None:  # pragma: no cover
                    raise RuntimeError("socket.recv() timed out ?") from exc
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
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(str(exc)) from exc

    @staticmethod
    def __next_packet_or_default(consumer: StreamDataConsumer[_ReceivedPacketT], default: _T) -> _ReceivedPacketT | _T:
        try:
            return next(consumer, default)
        except StreamProtocolParseError:
            raise
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(str(exc)) from exc

    def get_local_address(self) -> SocketAddress:
        return self.__addr

    def get_remote_address(self) -> SocketAddress:
        return self.__peer

    def fileno(self) -> int:
        with self.__lock:
            if self.__closed:
                return -1
            return self.__socket.fileno()

    @final
    def _get_buffer(self) -> bytes:
        return self.__consumer.get_unconsumed_data()

    @final
    def _check_not_closed(self) -> None:
        if self.__closed:
            raise OSError("Closed client")

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


@contextmanager
def _use_timeout(socket: _socket.socket, timeout: float | None) -> Iterator[None]:
    old_timeout: float | None = socket.gettimeout()
    if timeout != old_timeout:
        socket.settimeout(timeout)
    try:
        yield
    finally:
        socket.settimeout(old_timeout)
