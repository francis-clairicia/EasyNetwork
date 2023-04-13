# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Asynchronous network client module"""

from __future__ import annotations

__all__ = ["AsyncTCPNetworkClient"]

import errno as _errno
import socket as _socket
from typing import Any, Callable, Generic, Iterator, Mapping, Self, TypeVar, final

from ...exceptions import ClientClosedError, StreamProtocolParseError
from ...protocol import StreamProtocol
from ...tools._utils import (
    check_real_socket_state as _check_real_socket_state,
    concatenate_chunks as _concatenate_chunks,
    error_from_errno as _error_from_errno,
)
from ...tools.socket import MAX_STREAM_BUFSIZE, SocketAddress, SocketProxy, new_socket_address
from ...tools.stream import StreamDataConsumer
from ..backend.abc import AbstractAsyncBackend, AbstractAsyncStreamSocketAdapter, ILock
from ..backend.factory import AsyncBackendFactory
from .abc import AbstractAsyncNetworkClient

_ReceivedPacketT = TypeVar("_ReceivedPacketT")
_SentPacketT = TypeVar("_SentPacketT")


class AsyncTCPNetworkClient(AbstractAsyncNetworkClient[_SentPacketT, _ReceivedPacketT], Generic[_SentPacketT, _ReceivedPacketT]):
    __slots__ = (
        "__socket",
        "__backend",
        "__socket_proxy",
        "__receive_lock",
        "__send_lock",
        "__producer",
        "__consumer",
        "__addr",
        "__peer",
        "__eof_reached",
        "__max_recv_size",
    )

    def __init__(
        self,
        backend: AbstractAsyncBackend,
        socket: AbstractAsyncStreamSocketAdapter,
        protocol: StreamProtocol[_SentPacketT, _ReceivedPacketT],
        max_recv_size: int | None,
    ) -> None:
        super().__init__()
        if max_recv_size is None:
            max_recv_size = MAX_STREAM_BUFSIZE
        if not isinstance(max_recv_size, int) or max_recv_size <= 0:
            raise ValueError("'max_recv_size' must be a strictly positive integer")

        self.__socket: AbstractAsyncStreamSocketAdapter | None = socket
        self.__backend: AbstractAsyncBackend = backend
        self.__socket_proxy = SocketProxy(socket.socket())

        self.__receive_lock: ILock = backend.create_lock()
        self.__send_lock: ILock = backend.create_lock()

        self.__addr: SocketAddress = new_socket_address(socket.get_local_address(), self.__socket_proxy.family)
        self.__peer: SocketAddress = new_socket_address(socket.get_remote_address(), self.__socket_proxy.family)
        self.__producer: Callable[[_SentPacketT], Iterator[bytes]] = protocol.generate_chunks
        self.__consumer: StreamDataConsumer[_ReceivedPacketT] = StreamDataConsumer(protocol)
        self.__eof_reached: bool = False
        self.__max_recv_size: int = max_recv_size

        try:
            self.__socket_proxy.setsockopt(_socket.IPPROTO_TCP, _socket.TCP_NODELAY, True)
        except Exception:  # pragma: no cover
            pass

    def __repr__(self) -> str:
        try:
            socket = self.__socket
        except AttributeError:
            return f"<{type(self).__name__} closed>"
        return f"<{type(self).__name__} socket={socket!r}>"

    @classmethod
    async def connect(
        cls,
        address: tuple[str, int],
        protocol: StreamProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        family: int = 0,
        local_address: tuple[str, int] | None = None,
        happy_eyeballs_delay: float | None = None,
        max_recv_size: int | None = None,
        backend: str | AbstractAsyncBackend | None = None,
        backend_kwargs: Mapping[str, Any] | None = None,
    ) -> Self:
        backend = AsyncBackendFactory.ensure(backend, backend_kwargs)

        host, port = address
        socket_adapter = await backend.create_tcp_connection(
            host,
            port,
            family=family,
            happy_eyeballs_delay=happy_eyeballs_delay,
            local_address=local_address,
        )

        return cls(backend, socket_adapter, protocol, max_recv_size)

    @classmethod
    async def from_socket(
        cls,
        socket: _socket.socket,
        protocol: StreamProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        max_recv_size: int | None = None,
        backend: str | AbstractAsyncBackend | None = None,
        backend_kwargs: Mapping[str, Any] | None = None,
    ) -> Self:
        backend = AsyncBackendFactory.ensure(backend, backend_kwargs)

        socket_adapter = await backend.wrap_tcp_client_socket(socket)

        return cls(backend, socket_adapter, protocol, max_recv_size)

    @final
    def is_closing(self) -> bool:
        socket = self.__socket
        return socket is None or socket.is_closing()

    async def aclose(self) -> None:
        async with self.__send_lock:
            socket = self.__socket
            if socket is None:
                return
            self.__socket = None
            try:
                await socket.aclose()
            except ConnectionError:
                # It is normal if there was connection errors during operations. But do not propagate this exception,
                # as we will never reuse this socket
                pass

    async def abort(self) -> None:
        socket, self.__socket = self.__socket, None
        if socket is not None:
            await socket.abort()

    async def send_packet(self, packet: _SentPacketT) -> None:
        async with self.__send_lock:
            socket = self.__ensure_connected()
            await socket.sendall(_concatenate_chunks(self.__producer(packet)))
            _check_real_socket_state(self.__socket_proxy)

    async def recv_packet(self) -> _ReceivedPacketT:
        async with self.__receive_lock:
            consumer = self.__consumer
            next_packet = self.__next_packet
            try:
                return next_packet(consumer)  # If there is enough data from last call to create a packet, return immediately
            except StopIteration:
                pass
            socket = self.__ensure_connected()
            bufsize: int = self.__max_recv_size
            backend = self.__backend
            while True:
                chunk: bytes = await socket.recv(bufsize)
                if not chunk:
                    self.__eof_reached = True
                    raise _error_from_errno(_errno.ECONNABORTED)
                consumer.feed(chunk)
                del chunk
                try:
                    return next_packet(consumer)
                except StopIteration:
                    pass
                # Attempt failed, wait for one iteration
                await backend.coro_yield()

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
        socket = self.__socket
        if socket is None or socket.is_closing():
            return -1
        return self.__socket_proxy.fileno()

    def get_backend(self) -> AbstractAsyncBackend:
        return self.__backend

    def __ensure_connected(self) -> AbstractAsyncStreamSocketAdapter:
        socket = self.__socket
        if socket is None:
            raise ClientClosedError("Client is closing, or is already closed")
        if socket.is_closing() or self.__eof_reached:
            raise _error_from_errno(_errno.ECONNABORTED)
        return socket

    @property
    @final
    def socket(self) -> SocketProxy:
        return self.__socket_proxy

    @property
    @final
    def max_recv_size(self) -> int:
        return self.__max_recv_size
