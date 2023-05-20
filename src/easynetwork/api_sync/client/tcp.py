# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Network client module"""

from __future__ import annotations

__all__ = ["TCPNetworkClient"]

import errno as _errno
import socket as _socket
from threading import Lock as _Lock
from time import monotonic as _time_monotonic
from typing import Any, Callable, Generic, Iterator, TypeVar, final, overload

from ...exceptions import ClientClosedError, StreamProtocolParseError
from ...protocol import StreamProtocol
from ...tools._utils import (
    check_real_socket_state as _check_real_socket_state,
    check_socket_family as _check_socket_family,
    check_socket_no_ssl as _check_socket_no_ssl,
    concatenate_chunks as _concatenate_chunks,
    error_from_errno as _error_from_errno,
    replace_kwargs as _replace_kwargs,
    retry_socket_method as _retry_socket_method,
    set_tcp_nodelay as _set_tcp_nodelay,
)
from ...tools.socket import MAX_STREAM_BUFSIZE, SocketAddress, SocketProxy, new_socket_address
from ...tools.stream import StreamDataConsumer
from .abc import AbstractNetworkClient

_ReceivedPacketT = TypeVar("_ReceivedPacketT")
_SentPacketT = TypeVar("_SentPacketT")


class TCPNetworkClient(AbstractNetworkClient[_SentPacketT, _ReceivedPacketT], Generic[_SentPacketT, _ReceivedPacketT]):
    __slots__ = (
        "__socket",
        "__socket_proxy",
        "__send_lock",
        "__receive_lock",
        "__socket_lock",
        "__producer",
        "__consumer",
        "__addr",
        "__peer",
        "__eof_reached",
        "__max_recv_size",
    )

    @overload
    def __init__(
        self,
        address: tuple[str, int],
        /,
        protocol: StreamProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        connect_timeout: float | None = ...,
        local_address: tuple[str, int] | None = ...,
        max_recv_size: int | None = ...,
    ) -> None:
        ...

    @overload
    def __init__(
        self,
        socket: _socket.socket,
        /,
        protocol: StreamProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        max_recv_size: int | None = ...,
    ) -> None:
        ...

    def __init__(
        self,
        __arg: _socket.socket | tuple[str, int],
        /,
        protocol: StreamProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        max_recv_size: int | None = None,
        **kwargs: Any,
    ) -> None:
        self.__socket: _socket.socket | None = None  # If any exception occurs, the client will already be in a closed state
        super().__init__()
        self.__send_lock = _Lock()
        self.__receive_lock = _Lock()
        self.__socket_lock = _Lock()

        socket: _socket.socket
        match __arg:
            case _socket.socket() as socket if not kwargs:
                pass
            case (str(host), int(port)):
                _replace_kwargs(kwargs, {"local_address": "source_address", "connect_timeout": "timeout"})
                kwargs.setdefault("timeout", None)
                socket = _socket.create_connection((host, port), **kwargs, all_errors=True)
            case _:  # pragma: no cover
                raise TypeError("Invalid arguments")

        try:
            if socket.type != _socket.SOCK_STREAM:
                raise ValueError("Invalid socket type")

            _check_socket_family(socket.family)
            _check_socket_no_ssl(socket)

            if max_recv_size is None:
                max_recv_size = MAX_STREAM_BUFSIZE
            if not isinstance(max_recv_size, int) or max_recv_size <= 0:
                raise ValueError("'max_recv_size' must be a strictly positive integer")

            _set_tcp_nodelay(socket)
            socket.settimeout(0)  # Do not use global default timeout here

            self.__addr: SocketAddress = new_socket_address(socket.getsockname(), socket.family)
            self.__peer: SocketAddress = new_socket_address(socket.getpeername(), socket.family)
            self.__producer: Callable[[_SentPacketT], Iterator[bytes]] = protocol.generate_chunks
            self.__consumer: StreamDataConsumer[_ReceivedPacketT] = StreamDataConsumer(protocol)
            self.__socket_proxy = SocketProxy(socket, lock=self.__socket_lock)
            self.__eof_reached: bool = False
            self.__max_recv_size: int = max_recv_size
        except BaseException:
            socket.close()
            raise

        self.__socket = socket  # There was no errors

    def __del__(self) -> None:  # pragma: no cover
        try:
            socket: _socket.socket | None = self.__socket
        except AttributeError:
            return
        if socket is not None:
            socket.close()

    def __repr__(self) -> str:
        socket = self.__socket
        if socket is None:
            return f"<{type(self).__name__} closed>"
        return f"<{type(self).__name__} socket={socket!r}>"

    @final
    def is_closed(self) -> bool:
        with self.__socket_lock:
            return self.__socket is None

    def close(self) -> None:
        with self.__send_lock, self.__socket_lock:
            if (socket := self.__socket) is None:
                return
            self.__socket = None
            socket.close()

    def send_packet(self, packet: _SentPacketT) -> None:
        with self.__send_lock:
            socket = self.__ensure_connected()
            data: bytes = _concatenate_chunks(self.__producer(packet))
            buffer = memoryview(data)
            try:
                remaning: int = len(data)
                while remaning > 0:
                    nb_bytes_sent: int = _retry_socket_method(socket, None, "write", socket.send, buffer.toreadonly())
                    assert nb_bytes_sent >= 0, "socket.send() returns a negative integer"
                    _check_real_socket_state(socket)
                    remaning -= nb_bytes_sent
                    buffer = buffer[nb_bytes_sent:]
            finally:
                del buffer, data

    def recv_packet(self, timeout: float | None = None) -> _ReceivedPacketT:
        with self.__receive_lock:
            consumer = self.__consumer
            next_packet = self.__next_packet
            try:
                return next_packet(consumer)  # If there is enough data from last call to create a packet, return immediately
            except StopIteration:
                pass
            socket = self.__ensure_connected()
            bufsize: int = self.__max_recv_size
            monotonic = _time_monotonic  # pull function to local namespace

            while True:
                try:
                    _start = monotonic()
                    chunk: bytes = _retry_socket_method(socket, timeout, "read", socket.recv, bufsize)
                    _end = monotonic()
                except TimeoutError as exc:
                    if timeout is None:  # pragma: no cover
                        raise RuntimeError("socket.recv() timed out with timeout=None ?") from exc
                    break
                if not chunk:
                    self.__eof_reached = True
                    raise _error_from_errno(_errno.ECONNABORTED)
                consumer.feed(chunk)
                try:
                    return next_packet(consumer)
                except StopIteration:
                    if timeout is not None:
                        if timeout > 0:
                            timeout -= _end - _start
                        elif len(chunk) < bufsize:
                            break
                    continue
                finally:
                    del chunk
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

    def __ensure_connected(self) -> _socket.socket:
        if (socket := self.__socket) is None:
            raise ClientClosedError("Closed client")
        if self.__eof_reached:
            raise _error_from_errno(_errno.ECONNABORTED)
        return socket

    def get_local_address(self) -> SocketAddress:
        return self.__addr

    def get_remote_address(self) -> SocketAddress:
        return self.__peer

    def fileno(self) -> int:
        with self.__socket_lock:
            if (socket := self.__socket) is None:
                return -1
            return socket.fileno()

    @property
    @final
    def socket(self) -> SocketProxy:
        return self.__socket_proxy

    @property
    @final
    def max_recv_size(self) -> int:
        return self.__max_recv_size
