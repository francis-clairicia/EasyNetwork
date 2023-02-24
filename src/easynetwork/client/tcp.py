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
from threading import Lock
from time import monotonic as _time_monotonic
from typing import Any, Callable, Generic, Iterator, TypeVar, final, overload

from ..protocol import StreamProtocol, StreamProtocolParseError
from ..tools._utils import check_real_socket_state as _check_real_socket_state, restore_timeout_at_end as _restore_timeout_at_end
from ..tools.socket import MAX_STREAM_BUFSIZE, SocketAddress, SocketProxy, new_socket_address
from ..tools.stream import StreamDataConsumer
from .abc import AbstractNetworkClient
from .exceptions import ClientClosedError

_ReceivedPacketT = TypeVar("_ReceivedPacketT")
_SentPacketT = TypeVar("_SentPacketT")


class TCPNetworkClient(AbstractNetworkClient[_SentPacketT, _ReceivedPacketT], Generic[_SentPacketT, _ReceivedPacketT]):
    __slots__ = (
        "__socket",
        "__socket_proxy",
        "__owner",
        "__lock",
        "__producer",
        "__consumer",
        "__addr",
        "__peer",
        "__eof_reached",
        "__max_recv_bufsize",
    )

    @overload
    def __init__(
        self,
        address: tuple[str, int],
        /,
        protocol: StreamProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        timeout: float | None = ...,
        source_address: tuple[str, int] | None = ...,
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
        give: bool,
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
        self.__lock = Lock()

        socket: _socket.socket
        self.__owner: bool
        if isinstance(__arg, _socket.socket):
            try:
                give: bool = kwargs.pop("give")
            except KeyError:
                raise TypeError("Missing keyword argument 'give'") from None
            if kwargs:  # pragma: no cover
                raise TypeError("Invalid arguments")
            socket = __arg
            self.__owner = bool(give)
        elif isinstance(__arg, tuple):
            address: tuple[str, int] = __arg
            socket = _socket.create_connection(address, **kwargs)
            self.__owner = True
        else:  # pragma: no cover
            raise TypeError("Invalid arguments")

        try:
            if socket.type != _socket.SOCK_STREAM:
                raise ValueError("Invalid socket type")

            if max_recv_size is None:
                max_recv_size = MAX_STREAM_BUFSIZE
            if not isinstance(max_recv_size, int) or max_recv_size <= 0:
                raise ValueError("max_size must be a strict positive integer")

            self.__addr: SocketAddress = new_socket_address(socket.getsockname(), socket.family)
            self.__peer: SocketAddress = new_socket_address(socket.getpeername(), socket.family)
            self.__producer: Callable[[_SentPacketT], Iterator[bytes]] = protocol.generate_chunks
            self.__consumer: StreamDataConsumer[_ReceivedPacketT] = StreamDataConsumer(protocol)
            self.__socket_proxy = SocketProxy(socket, lock=self.__lock)
            self.__eof_reached: bool = False
            self.__max_recv_bufsize: int = max_recv_size
        except BaseException:
            if self.__owner:
                socket.close()
            raise

        self.__socket = socket  # There was no errors

    def __del__(self) -> None:  # pragma: no cover
        try:
            socket: _socket.socket | None = self.__socket
            owner: bool = self.__owner
        except AttributeError:
            return
        if owner and socket is not None:
            socket.close()

    def __repr__(self) -> str:
        socket = self.__socket
        if socket is None:
            return f"<{type(self).__name__} closed>"
        return f"<{type(self).__name__} socket={socket!r}>"

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

    def shutdown(self, how: int) -> None:
        with self.__lock:
            if (socket := self.__socket) is None:
                raise ClientClosedError("Closed client")
            socket.shutdown(how)

    def send_packet(self, packet: _SentPacketT) -> None:
        with self.__lock:
            if (socket := self.__socket) is None:
                raise ClientClosedError("Closed client")
            if self.__eof_reached:
                raise OSError(errno.ECONNABORTED, os.strerror(errno.ECONNABORTED))
            with _restore_timeout_at_end(socket):
                socket.settimeout(None)
                socket.sendall(b"".join(list(self.__producer(packet))))
                _check_real_socket_state(socket)

    def recv_packet(self, timeout: float | None = None) -> _ReceivedPacketT:
        with self.__lock:
            consumer = self.__consumer
            next_packet = self.__next_packet
            try:
                return next_packet(consumer)  # If there is enough data from last call to create a packet, return immediately
            except StopIteration:
                pass
            if (socket := self.__socket) is None:
                raise ClientClosedError("Closed client")
            if self.__eof_reached:  # Do not need to call socket.recv()
                raise OSError(errno.ECONNABORTED, os.strerror(errno.ECONNABORTED))
            bufsize: int = self.__max_recv_bufsize
            monotonic = _time_monotonic  # pull function to local namespace

            with _restore_timeout_at_end(socket):
                socket.settimeout(timeout)
                while True:
                    try:
                        _start = monotonic()
                        chunk: bytes = socket.recv(bufsize)
                        _end = monotonic()
                    except (TimeoutError, BlockingIOError) as exc:
                        if timeout is None:  # pragma: no cover
                            raise RuntimeError("socket.recv() timed out with timeout=None ?") from exc
                        break
                    if not chunk:
                        self.__eof_reached = True
                        raise OSError(errno.ECONNABORTED, os.strerror(errno.ECONNABORTED))
                    consumer.feed(chunk)
                    try:
                        return next_packet(consumer)
                    except StopIteration:
                        if timeout is not None:
                            if timeout > 0:
                                timeout -= _end - _start
                                if timeout < 0:  # pragma: no cover
                                    timeout = 0
                                socket.settimeout(timeout)
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

    def get_local_address(self) -> SocketAddress:
        return self.__addr

    def get_remote_address(self) -> SocketAddress:
        return self.__peer

    def fileno(self) -> int:
        with self.__lock:
            if (socket := self.__socket) is None:
                return -1
            return socket.fileno()

    @final
    def _get_buffer(self) -> bytes:
        return self.__consumer.get_unconsumed_data()

    @property
    @final
    def socket(self) -> SocketProxy:
        return self.__socket_proxy

    @property
    @final
    def max_recv_bufsize(self) -> int:
        return self.__max_recv_bufsize
