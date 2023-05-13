# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Asynchronous network client module"""

from __future__ import annotations

__all__ = ["AsyncTCPNetworkClient"]

import errno as _errno
import socket as _socket
from typing import Any, Callable, Generic, Iterator, Mapping, TypedDict, TypeVar, final, overload

from ...exceptions import ClientClosedError, StreamProtocolParseError
from ...protocol import StreamProtocol
from ...tools._utils import (
    check_real_socket_state as _check_real_socket_state,
    check_socket_family as _check_socket_family,
    concatenate_chunks as _concatenate_chunks,
    error_from_errno as _error_from_errno,
    set_tcp_nodelay as _set_tcp_nodelay,
)
from ...tools.socket import MAX_STREAM_BUFSIZE, SocketAddress, SocketProxy, new_socket_address
from ...tools.stream import StreamDataConsumer
from ..backend.abc import AbstractAsyncBackend, AbstractAsyncStreamSocketAdapter, ILock
from ..backend.factory import AsyncBackendFactory
from ..backend.tasks import SingleTaskRunner
from .abc import AbstractAsyncNetworkClient

_ReceivedPacketT = TypeVar("_ReceivedPacketT")
_SentPacketT = TypeVar("_SentPacketT")


class _ClientInfo(TypedDict):
    proxy: SocketProxy
    local_address: SocketAddress
    remote_address: SocketAddress


class AsyncTCPNetworkClient(AbstractAsyncNetworkClient[_SentPacketT, _ReceivedPacketT], Generic[_SentPacketT, _ReceivedPacketT]):
    __slots__ = (
        "__socket",
        "__backend",
        "__socket_connector",
        "__info",
        "__receive_lock",
        "__send_lock",
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
        family: int = ...,
        local_address: tuple[str, int] | None = ...,
        happy_eyeballs_delay: float | None = ...,
        max_recv_size: int | None = ...,
        backend: str | AbstractAsyncBackend | None = ...,
        backend_kwargs: Mapping[str, Any] | None = ...,
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
        backend: str | AbstractAsyncBackend | None = ...,
        backend_kwargs: Mapping[str, Any] | None = ...,
    ) -> None:
        ...

    def __init__(
        self,
        __arg: tuple[str, int] | _socket.socket,
        /,
        protocol: StreamProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        max_recv_size: int | None = None,
        backend: str | AbstractAsyncBackend | None = None,
        backend_kwargs: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        backend = AsyncBackendFactory.ensure(backend, backend_kwargs)
        if max_recv_size is None:
            max_recv_size = MAX_STREAM_BUFSIZE
        if not isinstance(max_recv_size, int) or max_recv_size <= 0:
            raise ValueError("'max_recv_size' must be a strictly positive integer")

        self.__socket: AbstractAsyncStreamSocketAdapter | None = None
        self.__backend: AbstractAsyncBackend = backend
        self.__info: _ClientInfo | None = None

        self.__socket_connector: SingleTaskRunner[AbstractAsyncStreamSocketAdapter] | None = None
        match __arg:
            case _socket.socket() as socket:
                self.__socket_connector = SingleTaskRunner(backend, backend.wrap_tcp_client_socket, socket, **kwargs)
            case (host, port):
                self.__socket_connector = SingleTaskRunner(backend, backend.create_tcp_connection, host, port, **kwargs)
            case _:  # pragma: no cover
                raise TypeError("Invalid arguments")

        self.__receive_lock: ILock = backend.create_lock()
        self.__send_lock: ILock = backend.create_lock()
        self.__producer: Callable[[_SentPacketT], Iterator[bytes]] = protocol.generate_chunks
        self.__consumer: StreamDataConsumer[_ReceivedPacketT] = StreamDataConsumer(protocol)
        self.__eof_reached: bool = False
        self.__max_recv_size: int = max_recv_size

    def __repr__(self) -> str:
        try:
            socket = self.__socket
        except AttributeError:
            return f"<{type(self).__name__} (partially initialized)>"
        return f"<{type(self).__name__} socket={socket!r}>"

    async def wait_connected(self) -> None:
        if self.__socket is not None:
            return
        if self.__socket_connector is None:
            raise ClientClosedError("Client is closing, or is already closed")
        self.__socket = await self.__socket_connector.run()
        self.__socket_connector = None
        if self.__info is not None:  # pragma: no cover
            return
        socket_proxy = SocketProxy(self.__socket.socket())
        _check_socket_family(socket_proxy.family)
        local_address: SocketAddress = new_socket_address(self.__socket.get_local_address(), socket_proxy.family)
        remote_address: SocketAddress = new_socket_address(self.__socket.get_remote_address(), socket_proxy.family)
        self.__info = {
            "proxy": socket_proxy,
            "local_address": local_address,
            "remote_address": remote_address,
        }
        _set_tcp_nodelay(socket_proxy)

    def is_connected(self) -> bool:
        return self.__socket is not None

    @final
    def is_closing(self) -> bool:
        if self.__socket_connector is not None:
            return False
        socket = self.__socket
        return socket is None or socket.is_closing()

    async def aclose(self) -> None:
        if self.__socket_connector is not None:
            self.__socket_connector.cancel()
            self.__socket_connector = None
        async with self.__send_lock:
            socket, self.__socket = self.__socket, None
            if socket is None:
                return
            try:
                await socket.aclose()
            except ConnectionError:
                # It is normal if there was connection errors during operations. But do not propagate this exception,
                # as we will never reuse this socket
                pass
            except self.__backend.get_cancelled_exc_class():
                try:
                    await socket.abort()
                finally:
                    raise

    async def send_packet(self, packet: _SentPacketT) -> None:
        async with self.__send_lock:
            socket = await self.__ensure_connected()
            await socket.sendall(_concatenate_chunks(self.__producer(packet)))
            _check_real_socket_state(self.socket)

    async def recv_packet(self) -> _ReceivedPacketT:
        async with self.__receive_lock:
            consumer = self.__consumer
            next_packet = self.__next_packet
            try:
                return next_packet(consumer)  # If there is enough data from last call to create a packet, return immediately
            except StopIteration:
                pass
            socket = await self.__ensure_connected()
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
        if self.__info is None:
            raise _error_from_errno(_errno.ENOTSOCK)
        return self.__info["local_address"]

    def get_remote_address(self) -> SocketAddress:
        if self.__info is None:
            raise _error_from_errno(_errno.ENOTSOCK)
        return self.__info["remote_address"]

    def fileno(self) -> int:
        socket = self.__socket
        if socket is None or socket.is_closing():
            return -1
        return socket.socket().fileno()

    def get_backend(self) -> AbstractAsyncBackend:
        return self.__backend

    async def __ensure_connected(self) -> AbstractAsyncStreamSocketAdapter:
        await self.wait_connected()
        assert self.__socket is not None
        if self.__socket.is_closing() or self.__eof_reached:
            raise _error_from_errno(_errno.ECONNABORTED)
        return self.__socket

    @property
    @final
    def socket(self) -> SocketProxy:
        if self.__info is None:
            raise _error_from_errno(_errno.ENOTSOCK)
        return self.__info["proxy"]

    @property
    @final
    def max_recv_size(self) -> int:
        return self.__max_recv_size
