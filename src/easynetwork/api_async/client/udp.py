# Copyright 2021-2023, Francis Clairicia-Rose-Claire-Josephine
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
#
"""Asynchronous network client module"""

from __future__ import annotations

__all__ = ["AsyncUDPNetworkClient", "AsyncUDPNetworkEndpoint"]

import errno as _errno
import socket as _socket
from collections.abc import AsyncIterator, Mapping
from typing import TYPE_CHECKING, Any, Generic, Self, TypedDict, final, overload

from ..._typevars import _ReceivedPacketT, _SentPacketT
from ...exceptions import ClientClosedError, DatagramProtocolParseError
from ...protocol import DatagramProtocol
from ...tools._utils import (
    check_real_socket_state as _check_real_socket_state,
    check_socket_family as _check_socket_family,
    check_socket_no_ssl as _check_socket_no_ssl,
    ensure_datagram_socket_bound as _ensure_datagram_socket_bound,
    error_from_errno as _error_from_errno,
)
from ...tools.constants import MAX_DATAGRAM_BUFSIZE
from ...tools.socket import SocketAddress, SocketProxy, new_socket_address
from ..backend.abc import AbstractAsyncBackend, AbstractAsyncDatagramSocketAdapter, ILock
from ..backend.factory import AsyncBackendFactory
from ..backend.tasks import SingleTaskRunner
from .abc import AbstractAsyncNetworkClient

if TYPE_CHECKING:
    from types import TracebackType


class _EndpointInfo(TypedDict):
    proxy: SocketProxy
    local_address: SocketAddress
    remote_address: SocketAddress | None


class AsyncUDPNetworkEndpoint(Generic[_SentPacketT, _ReceivedPacketT]):
    __slots__ = (
        "__socket",
        "__backend",
        "__socket_builder",
        "__info",
        "__receive_lock",
        "__send_lock",
        "__protocol",
        "__weakref__",
    )

    @overload
    def __init__(
        self,
        protocol: DatagramProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        local_address: tuple[str | None, int] | None = ...,
        remote_address: tuple[str, int] | None = ...,
        reuse_port: bool = ...,
        backend: str | AbstractAsyncBackend | None = ...,
        backend_kwargs: Mapping[str, Any] | None = ...,
    ) -> None:
        ...

    @overload
    def __init__(
        self,
        protocol: DatagramProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        socket: _socket.socket,
        backend: str | AbstractAsyncBackend | None = ...,
        backend_kwargs: Mapping[str, Any] | None = ...,
    ) -> None:
        ...

    def __init__(
        self,
        protocol: DatagramProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        backend: str | AbstractAsyncBackend | None = None,
        backend_kwargs: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        backend = AsyncBackendFactory.ensure(backend, backend_kwargs)

        if not isinstance(protocol, DatagramProtocol):
            raise TypeError(f"Expected a DatagramProtocol object, got {protocol!r}")

        self.__protocol: DatagramProtocol[_SentPacketT, _ReceivedPacketT] = protocol
        self.__socket: AbstractAsyncDatagramSocketAdapter | None = None
        self.__backend: AbstractAsyncBackend = backend
        self.__info: _EndpointInfo | None = None

        self.__socket_builder: SingleTaskRunner[AbstractAsyncDatagramSocketAdapter] | None = None
        match kwargs:
            case {"socket": _socket.socket() as socket, **kwargs}:
                _check_socket_family(socket.family)
                _check_socket_no_ssl(socket)
                _ensure_datagram_socket_bound(socket)
                self.__socket_builder = SingleTaskRunner(backend, backend.wrap_udp_socket, socket, **kwargs)
            case _:
                if kwargs.get("local_address") is None:
                    kwargs["local_address"] = ("localhost", 0)
                self.__socket_builder = SingleTaskRunner(backend, backend.create_udp_endpoint, **kwargs)

        self.__receive_lock: ILock = backend.create_lock()
        self.__send_lock: ILock = backend.create_lock()

    def __repr__(self) -> str:
        try:
            socket = self.__socket
        except AttributeError:
            return f"<{type(self).__name__} (partially initialized)>"
        return f"<{type(self).__name__} socket={socket!r}>"

    async def __aenter__(self) -> Self:
        await self.wait_bound()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    def __getstate__(self) -> Any:  # pragma: no cover
        raise TypeError(f"cannot pickle {self.__class__.__name__!r} object")

    def is_bound(self) -> bool:
        return self.__socket is not None and self.__info is not None

    async def wait_bound(self) -> None:
        if self.__socket is None:
            socket_builder = self.__socket_builder
            if socket_builder is None:
                raise ClientClosedError("Client is closing, or is already closed")
            socket = await socket_builder.run()
            if self.__socket_builder is None:  # wait_bound() or aclose() called in concurrency
                return await self.__backend.cancel_shielded_coro_yield()
            self.__socket = socket
            self.__socket_builder = None
        if self.__info is None:
            self.__info = self.__build_info_dict(self.__socket)

    @staticmethod
    def __build_info_dict(socket: AbstractAsyncDatagramSocketAdapter) -> _EndpointInfo:
        socket_proxy = SocketProxy(socket.socket())
        local_address: SocketAddress = new_socket_address(socket.get_local_address(), socket_proxy.family)
        if local_address.port == 0:
            raise AssertionError(f"{socket} is not bound to a local address")
        remote_address: SocketAddress | None
        if (peername := socket.get_remote_address()) is None:
            remote_address = None
        else:
            remote_address = new_socket_address(peername, socket_proxy.family)
        return {
            "proxy": socket_proxy,
            "local_address": local_address,
            "remote_address": remote_address,
        }

    @final
    def is_closing(self) -> bool:
        if self.__socket_builder is not None:
            return False
        socket = self.__socket
        return socket is None or socket.is_closing()

    async def aclose(self) -> None:
        if self.__socket_builder is not None:
            self.__socket_builder.cancel()
            self.__socket_builder = None
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

    async def send_packet_to(
        self,
        packet: _SentPacketT,
        address: tuple[str, int] | tuple[str, int, int, int] | None,
    ) -> None:
        async with self.__send_lock:
            socket = await self.__ensure_opened()
            assert self.__info is not None  # nosec assert_used
            if (remote_addr := self.__info["remote_address"]) is not None:
                if address is not None:
                    if new_socket_address(address, self.socket.family) != remote_addr:
                        raise ValueError(f"Invalid address: must be None or {remote_addr}")
                    address = None
            elif address is None:
                raise ValueError("Invalid address: must not be None")
            data: bytes = self.__protocol.make_datagram(packet)
            await socket.sendto(data, address)
            _check_real_socket_state(self.socket)

    async def recv_packet_from(self) -> tuple[_ReceivedPacketT, SocketAddress]:
        async with self.__receive_lock:
            socket = await self.__ensure_opened()
            data, sender = await socket.recvfrom(MAX_DATAGRAM_BUFSIZE)
            sender = new_socket_address(sender, self.socket.family)
            try:
                return self.__protocol.build_packet_from_datagram(data), sender
            except DatagramProtocolParseError as exc:
                exc.sender_address = sender
                raise
            finally:
                del data

    async def iter_received_packets_from(self) -> AsyncIterator[tuple[_ReceivedPacketT, SocketAddress]]:
        while True:
            try:
                packet_tuple = await self.recv_packet_from()
            except OSError:
                return
            yield packet_tuple

    def get_local_address(self) -> SocketAddress:
        if self.__info is None:
            raise _error_from_errno(_errno.ENOTSOCK)
        return self.__info["local_address"]

    def get_remote_address(self) -> SocketAddress | None:
        if self.__info is None:
            raise _error_from_errno(_errno.ENOTSOCK)
        return self.__info["remote_address"]

    def fileno(self) -> int:
        socket = self.__socket
        if socket is None:
            return -1
        return socket.socket().fileno()

    def get_backend(self) -> AbstractAsyncBackend:
        return self.__backend

    async def __ensure_opened(self) -> AbstractAsyncDatagramSocketAdapter:
        await self.wait_bound()
        assert self.__socket is not None  # nosec assert_used
        if self.__socket.is_closing():
            raise _error_from_errno(_errno.ECONNABORTED)
        return self.__socket

    @property
    @final
    def socket(self) -> SocketProxy:
        if self.__info is None:
            raise AttributeError("Socket not connected")
        return self.__info["proxy"]


class AsyncUDPNetworkClient(AbstractAsyncNetworkClient[_SentPacketT, _ReceivedPacketT], Generic[_SentPacketT, _ReceivedPacketT]):
    __slots__ = ("__endpoint",)

    @overload
    def __init__(
        self,
        address: tuple[str, int],
        /,
        protocol: DatagramProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        local_address: tuple[str, int] | None = ...,
        reuse_port: bool = ...,
        backend: str | AbstractAsyncBackend | None = ...,
        backend_kwargs: Mapping[str, Any] | None = ...,
    ) -> None:
        ...

    @overload
    def __init__(
        self,
        socket: _socket.socket,
        /,
        protocol: DatagramProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        backend: str | AbstractAsyncBackend | None = ...,
        backend_kwargs: Mapping[str, Any] | None = ...,
    ) -> None:
        ...

    def __init__(
        self,
        __arg: tuple[str, int] | _socket.socket,
        /,
        protocol: DatagramProtocol[_SentPacketT, _ReceivedPacketT],
        **kwargs: Any,
    ) -> None:
        super().__init__()

        endpoint: AsyncUDPNetworkEndpoint[_SentPacketT, _ReceivedPacketT]
        match __arg:
            case _socket.socket() as socket:
                try:
                    socket.getpeername()
                except OSError as exc:
                    raise OSError("No remote address configured") from exc
                endpoint = AsyncUDPNetworkEndpoint(protocol=protocol, socket=socket, **kwargs)
            case (host, port):
                endpoint = AsyncUDPNetworkEndpoint(protocol=protocol, remote_address=(host, port), **kwargs)
            case _:  # pragma: no cover
                raise TypeError("Invalid arguments")

        self.__endpoint: AsyncUDPNetworkEndpoint[_SentPacketT, _ReceivedPacketT] = endpoint

    def __repr__(self) -> str:
        try:
            return f"<{type(self).__name__} endpoint={self.__endpoint!r}>"
        except AttributeError:
            return f"<{type(self).__name__} (partially initialized)>"

    def is_connected(self) -> bool:
        return self.__endpoint.is_bound() and self.__endpoint.get_remote_address() is not None

    async def wait_connected(self) -> None:
        await self.__endpoint.wait_bound()
        self.__check_remote_address()

    @final
    def is_closing(self) -> bool:
        return self.__endpoint.is_closing()

    async def aclose(self) -> None:
        return await self.__endpoint.aclose()

    async def send_packet(self, packet: _SentPacketT) -> None:
        await self.wait_connected()
        return await self.__endpoint.send_packet_to(packet, None)

    async def recv_packet(self) -> _ReceivedPacketT:
        await self.wait_connected()
        packet, _ = await self.__endpoint.recv_packet_from()
        return packet

    async def iter_received_packets(self) -> AsyncIterator[_ReceivedPacketT]:
        await self.wait_connected()
        async for packet, _ in self.__endpoint.iter_received_packets_from():
            yield packet

    def get_local_address(self) -> SocketAddress:
        return self.__endpoint.get_local_address()

    def get_remote_address(self) -> SocketAddress:
        remote_address: SocketAddress = self.__check_remote_address()
        return remote_address

    def fileno(self) -> int:
        return self.__endpoint.fileno()

    def get_backend(self) -> AbstractAsyncBackend:
        return self.__endpoint.get_backend()

    def __check_remote_address(self) -> SocketAddress:
        remote_address: SocketAddress | None = self.__endpoint.get_remote_address()
        if remote_address is None:
            raise OSError("No remote address configured") from _error_from_errno(_errno.ENOTCONN)
        return remote_address

    @property
    @final
    def socket(self) -> SocketProxy:
        return self.__endpoint.socket
