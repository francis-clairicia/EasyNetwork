# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Network client module"""

from __future__ import annotations

__all__ = ["TCPNetworkClient"]

import errno
import os
import socket as _socket
from contextlib import contextmanager
from threading import Lock
from time import monotonic as _time_monotonic
from typing import Any, Generic, Iterator, TypeVar, final, overload

from ..protocol import StreamProtocol, StreamProtocolParseError
from ..tools.socket import MAX_STREAM_BUFSIZE, SocketAddress, SocketProxy, new_socket_address
from ..tools.stream import StreamDataConsumer, StreamDataProducer
from .abc import AbstractNetworkClient

_ReceivedPacketT = TypeVar("_ReceivedPacketT")
_SentPacketT = TypeVar("_SentPacketT")


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
        self.__closed: bool = True  # If any exception occurs, the client will already be in a closed state
        super().__init__()
        self.__lock = Lock()
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
        self.__closed = False  # There was no errors

    def __repr__(self) -> str:
        try:
            socket = self.__socket
        except AttributeError:
            return f"<{type(self).__name__} closed>"
        return f"<{type(self).__name__} socket={socket!r}>"

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
            if self.__closed:
                raise OSError(errno.EPIPE, os.strerror(errno.EPIPE))
            socket: _socket.socket = self.__socket
            with _restore_timeout_at_end(socket):
                socket.settimeout(None)
                self.__producer.queue(packet)
                socket.sendall(b"".join(list(self.__producer)), self.__default_send_flags)

    def recv_packet(self, timeout: float | None = None) -> _ReceivedPacketT:
        with self.__lock:
            consumer = self.__consumer
            next_packet = self.__next_packet
            try:
                return next_packet(consumer)  # If there is enough data from last call to create a packet, return immediately
            except StopIteration:
                pass
            if self.__closed or self.__eof_reached:  # Do not need to call socket.recv()
                raise EOFError("Closed connection")
            flags = self.__default_recv_flags
            socket: _socket.socket = self.__socket
            socket_recv = socket.recv
            socket_settimeout = socket.settimeout
            bufsize: int = self.max_size
            monotonic = _time_monotonic  # pull function to local namespace

            with _restore_timeout_at_end(socket):
                socket_settimeout(timeout)
                while True:
                    try:
                        _start = monotonic()
                        chunk: bytes = socket_recv(bufsize, flags)
                        _end = monotonic()
                    except (TimeoutError, BlockingIOError) as exc:
                        if timeout is None:  # pragma: no cover
                            raise RuntimeError("socket.recv() timed out with timeout=None ?") from exc
                        break
                    if not chunk:
                        self.__eof_reached = True
                        raise EOFError("Closed connection")
                    try:
                        consumer.feed(chunk)
                    finally:
                        del chunk
                    try:
                        return next_packet(consumer)
                    except StopIteration:
                        if timeout is not None and timeout > 0:
                            timeout -= _end - _start
                            if timeout < 0:  # pragma: no cover
                                timeout = 0
                            socket_settimeout(timeout)
                        continue
                # Loop break
                raise TimeoutError("recv_packet() timed out")

    @staticmethod
    def __next_packet(consumer: StreamDataConsumer[_ReceivedPacketT]) -> _ReceivedPacketT:
        try:
            return next(consumer)
        except (StopIteration, StreamProtocolParseError):
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
def _restore_timeout_at_end(socket: _socket.socket) -> Iterator[float | None]:
    old_timeout: float | None = socket.gettimeout()
    try:
        yield old_timeout
    finally:
        socket.settimeout(old_timeout)
