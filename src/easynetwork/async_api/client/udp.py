# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Asynchronous network client module"""

from __future__ import annotations

__all__ = ["AsyncUDPNetworkClient", "AsyncUDPNetworkEndpoint"]

import concurrent.futures
import errno as _errno
from typing import TYPE_CHECKING, Any, AsyncIterator, Generic, Mapping, TypeVar, final

from ...exceptions import ClientClosedError, DatagramProtocolParseError
from ...protocol import DatagramProtocol
from ...tools._utils import check_real_socket_state as _check_real_socket_state, error_from_errno as _error_from_errno
from ...tools.socket import SocketAddress, SocketProxy, new_socket_address
from ..backend._utils import run_task_once as _run_task_once
from ..backend.abc import AbstractAsyncBackend, AbstractDatagramSocketAdapter, ILock
from ..backend.factory import AsyncBackendFactory
from .abc import AbstractAsyncNetworkClient

if TYPE_CHECKING:
    import socket as _socket
    from types import TracebackType

_ReceivedPacketT = TypeVar("_ReceivedPacketT")
_SentPacketT = TypeVar("_SentPacketT")


class AsyncUDPNetworkEndpoint(Generic[_SentPacketT, _ReceivedPacketT]):
    __slots__ = (
        "__socket",
        "__backend",
        "__socket_proxy",
        "__receive_lock",
        "__send_lock",
        "__protocol",
        "__addr",
        "__peer",
        "__closed",
        "__close_waiter",
        "__weakref__",
    )

    if TYPE_CHECKING:
        __Self = TypeVar("__Self", bound="AsyncUDPNetworkEndpoint[Any, Any]")

    def __init__(
        self,
        socket: AbstractDatagramSocketAdapter,
        protocol: DatagramProtocol[_SentPacketT, _ReceivedPacketT],
    ) -> None:
        super().__init__()
        backend = socket.get_backend()

        self.__socket: AbstractDatagramSocketAdapter = socket
        self.__backend: AbstractAsyncBackend = backend
        self.__socket_proxy = socket.proxy()

        self.__receive_lock: ILock = backend.create_lock()
        self.__send_lock: ILock = backend.create_lock()

        self.__addr: SocketAddress = new_socket_address(socket.getsockname(), self.__socket_proxy.family)
        self.__peer: SocketAddress | None = (
            new_socket_address(peername, self.__socket_proxy.family) if (peername := socket.getpeername()) is not None else None
        )
        self.__protocol: DatagramProtocol[_SentPacketT, _ReceivedPacketT] = protocol
        self.__closed: bool = False
        self.__close_waiter: concurrent.futures.Future[None] = concurrent.futures.Future()

        if self.__addr.port == 0:
            raise OSError(f"{socket} is not bound to a local address")

    def __repr__(self) -> str:
        try:
            socket = self.__socket
        except AttributeError:
            return f"<{type(self).__name__} closed>"
        return f"<{type(self).__name__} socket={socket!r}>"

    async def __aenter__(self: __Self) -> __Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.close()

    def __getstate__(self) -> Any:  # pragma: no cover
        raise TypeError(f"cannot pickle {self.__class__.__name__!r} object")

    @classmethod
    async def create(
        cls: type[__Self],
        protocol: DatagramProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        local_address: tuple[str, int] | None = None,
        remote_address: tuple[str, int] | None = None,
        backend: str | AbstractAsyncBackend | None = None,
        backend_kwargs: Mapping[str, Any] | None = None,
    ) -> __Self:
        if not isinstance(backend, AbstractAsyncBackend):
            if backend_kwargs is None:
                backend_kwargs = {}
            backend = AsyncBackendFactory.new(backend, **backend_kwargs)

        if local_address is None:
            local_address = ("", 0)

        socket_adapter = await backend.create_udp_endpoint(
            local_address=local_address,
            remote_address=remote_address,
        )

        return cls(socket_adapter, protocol)

    @classmethod
    async def from_socket(
        cls: type[__Self],
        socket: _socket.socket,
        protocol: DatagramProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        backend: str | AbstractAsyncBackend | None = None,
        backend_kwargs: Mapping[str, Any] | None = None,
    ) -> __Self:
        if not isinstance(backend, AbstractAsyncBackend):
            if backend_kwargs is None:
                backend_kwargs = {}
            backend = AsyncBackendFactory.new(backend, **backend_kwargs)

        if socket.getsockname()[1] == 0:
            socket.bind(("", 0))
        socket_adapter = await backend.wrap_udp_socket(socket)

        return cls(socket_adapter, protocol)

    @final
    def is_closing(self) -> bool:
        return self.__closed or self.__close_waiter.running()

    async def close(self) -> None:
        await _run_task_once(self.__close, self.__close_waiter, self.__backend)

    async def __close(self) -> None:
        async with self.__receive_lock, self.__send_lock:
            self.__closed = True
        try:
            await self.__socket.close()
        except ConnectionError:
            # It is normal if there was connection errors during operations. But do not propagate this exception,
            # as we will never reuse this socket
            pass

    async def send_packet_to(
        self,
        packet: _SentPacketT,
        address: tuple[str, int] | tuple[str, int, int, int] | None,
    ) -> None:
        async with self.__send_lock:
            socket = self.__ensure_opened()
            if (remote_addr := self.__peer) is not None:
                if address is not None:
                    if new_socket_address(address, self.__socket_proxy.family) != remote_addr:
                        raise ValueError(f"Invalid address: must be None or {remote_addr}")
                    address = None
            elif address is None:
                raise ValueError("Invalid address: must not be None")
            data: bytes = self.__protocol.make_datagram(packet)
            await socket.sendto(data, address)
            _check_real_socket_state(self.__socket_proxy)

    async def recv_packet_from(self) -> tuple[_ReceivedPacketT, SocketAddress]:
        async with self.__receive_lock:
            socket = self.__ensure_opened()
            data, sender = await socket.recvfrom()
            try:
                return self.__protocol.build_packet_from_datagram(data), new_socket_address(sender, self.__socket_proxy.family)
            except DatagramProtocolParseError:
                raise
            except Exception as exc:  # pragma: no cover
                raise RuntimeError(str(exc)) from exc
            finally:
                del data

    async def iter_received_packets_from(self) -> AsyncIterator[tuple[_ReceivedPacketT, SocketAddress]]:
        recv_packet_from = self.recv_packet_from

        while True:
            try:
                packet_tuple = await recv_packet_from()
            except OSError:
                return
            yield packet_tuple

    def get_local_address(self) -> SocketAddress:
        return self.__addr

    def get_remote_address(self) -> SocketAddress | None:
        return self.__peer

    def fileno(self) -> int:
        if self.__closed or self.__socket.is_closing():
            return -1
        return self.__socket_proxy.fileno()

    def __ensure_opened(self) -> AbstractDatagramSocketAdapter:
        if self.__closed:
            raise ClientClosedError("Client is closing, or is already closed")
        socket = self.__socket
        if socket.is_closing():
            raise _error_from_errno(_errno.ECONNABORTED)
        return socket

    @property
    @final
    def socket(self) -> SocketProxy:
        return self.__socket_proxy


class AsyncUDPNetworkClient(AbstractAsyncNetworkClient[_SentPacketT, _ReceivedPacketT], Generic[_SentPacketT, _ReceivedPacketT]):
    __slots__ = ("__endpoint", "__peer")

    if TYPE_CHECKING:
        __Self = TypeVar("__Self", bound="AsyncUDPNetworkClient[Any, Any]")

    def __init__(
        self,
        socket: AbstractDatagramSocketAdapter,
        protocol: DatagramProtocol[_SentPacketT, _ReceivedPacketT],
    ) -> None:
        super().__init__()

        endpoint: AsyncUDPNetworkEndpoint[_SentPacketT, _ReceivedPacketT] = AsyncUDPNetworkEndpoint(socket, protocol)
        self.__endpoint: AsyncUDPNetworkEndpoint[_SentPacketT, _ReceivedPacketT] = endpoint
        remote_address = endpoint.get_remote_address()
        if remote_address is None:
            raise OSError("No remote address configured")
        self.__peer: SocketAddress = remote_address

    def __repr__(self) -> str:
        try:
            return f"<{type(self).__name__} endpoint={self.__endpoint!r}>"
        except AttributeError:
            return f"<{type(self).__name__} (partially initialized)>"

    @classmethod
    async def create(
        cls: type[__Self],
        remote_address: tuple[str, int],
        protocol: DatagramProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        local_address: tuple[str, int] | None = None,
        backend: str | AbstractAsyncBackend | None = None,
        backend_kwargs: Mapping[str, Any] | None = None,
    ) -> __Self:
        if not isinstance(backend, AbstractAsyncBackend):
            if backend_kwargs is None:
                backend_kwargs = {}
            backend = AsyncBackendFactory.new(backend, **backend_kwargs)

        if local_address is None:
            local_address = ("", 0)

        remote_host, remote_port = remote_address
        socket_adapter = await backend.create_udp_endpoint(
            local_address=local_address,
            remote_address=(remote_host, remote_port),
        )
        return cls(socket_adapter, protocol)

    @classmethod
    async def from_socket(
        cls: type[__Self],
        socket: _socket.socket,
        protocol: DatagramProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        backend: str | AbstractAsyncBackend | None = None,
        backend_kwargs: Mapping[str, Any] | None = None,
    ) -> __Self:
        if not isinstance(backend, AbstractAsyncBackend):
            if backend_kwargs is None:
                backend_kwargs = {}
            backend = AsyncBackendFactory.new(backend, **backend_kwargs)

        if socket.getsockname()[1] == 0:
            socket.bind(("", 0))
        socket_adapter = await backend.wrap_udp_socket(socket)

        return cls(socket_adapter, protocol)

    @final
    def is_closing(self) -> bool:
        return self.__endpoint.is_closing()

    async def close(self) -> None:
        return await self.__endpoint.close()

    async def send_packet(self, packet: _SentPacketT) -> None:
        return await self.__endpoint.send_packet_to(packet, None)

    async def recv_packet(self) -> _ReceivedPacketT:
        packet, _ = await self.__endpoint.recv_packet_from()
        return packet

    async def iter_received_packets(self) -> AsyncIterator[_ReceivedPacketT]:
        async for packet, _ in self.__endpoint.iter_received_packets_from():
            yield packet

    def get_local_address(self) -> SocketAddress:
        return self.__endpoint.get_local_address()

    def get_remote_address(self) -> SocketAddress:
        return self.__peer

    def fileno(self) -> int:
        return self.__endpoint.fileno()

    @property
    @final
    def socket(self) -> SocketProxy:
        return self.__endpoint.socket
