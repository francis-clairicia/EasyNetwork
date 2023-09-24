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

import contextlib
import dataclasses as _dataclasses
import errno as _errno
import math
import socket as _socket
import time
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping
from typing import TYPE_CHECKING, Any, Generic, Self, final, overload

from ..._typevars import _ReceivedPacketT, _SentPacketT
from ...exceptions import ClientClosedError, DatagramProtocolParseError
from ...protocol import DatagramProtocol
from ...tools._utils import (
    check_real_socket_state as _check_real_socket_state,
    check_socket_family as _check_socket_family,
    check_socket_no_ssl as _check_socket_no_ssl,
    ensure_datagram_socket_bound as _ensure_datagram_socket_bound,
    error_from_errno as _error_from_errno,
    make_callback as _make_callback,
)
from ...tools.constants import MAX_DATAGRAM_BUFSIZE
from ...tools.socket import SocketAddress, SocketProxy, new_socket_address
from ..backend.abc import AsyncBackend, AsyncDatagramSocketAdapter, CancelScope, ILock
from ..backend.factory import AsyncBackendFactory
from .abc import AbstractAsyncNetworkClient

if TYPE_CHECKING:
    from types import TracebackType


@_dataclasses.dataclass(kw_only=True, frozen=True, slots=True)
class _EndpointInfo:
    proxy: SocketProxy
    local_address: SocketAddress
    remote_address: SocketAddress | None


@_dataclasses.dataclass(kw_only=True, slots=True)
class _SocketConnector:
    lock: ILock
    factory: Callable[[], Awaitable[tuple[AsyncDatagramSocketAdapter, _EndpointInfo]]] | None
    scope: CancelScope
    _result: tuple[AsyncDatagramSocketAdapter, _EndpointInfo] | None = _dataclasses.field(init=False, default=None)

    async def get(self) -> tuple[AsyncDatagramSocketAdapter, _EndpointInfo] | None:
        async with self.lock:
            factory, self.factory = self.factory, None
            if factory is not None:
                with self.scope:
                    self._result = await factory()
        return self._result


class AsyncUDPNetworkEndpoint(Generic[_SentPacketT, _ReceivedPacketT]):
    """Asynchronous generic UDP endpoint interface.

    See Also:
        :class:`.AsyncUDPNetworkServer`
            An advanced API for handling datagrams.
    """

    __slots__ = (
        "__socket",
        "__backend",
        "__socket_connector",
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
        backend: str | AsyncBackend | None = ...,
        backend_kwargs: Mapping[str, Any] | None = ...,
    ) -> None:
        ...

    @overload
    def __init__(
        self,
        protocol: DatagramProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        socket: _socket.socket,
        backend: str | AsyncBackend | None = ...,
        backend_kwargs: Mapping[str, Any] | None = ...,
    ) -> None:
        ...

    def __init__(
        self,
        protocol: DatagramProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        backend: str | AsyncBackend | None = None,
        backend_kwargs: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Common Parameters:
            protocol: The :term:`protocol object` to use.

        Connection Parameters:
            remote_address: If given, is a ``(host, port)`` tuple used to connect the socket.
            local_address: If given, is a ``(local_host, local_port)`` tuple used to bind the socket locally.
            reuse_port: Tells the kernel to allow this endpoint to be bound to the same port as other existing
                        endpoints are bound to, so long as they all set this flag when being created.
                        This option is not supported on Windows and some Unixes.
                        If the SO_REUSEPORT constant is not defined then this capability is unsupported.

        Socket Parameters:
            socket: An already connected UDP :class:`socket.socket`. If `socket` is given,
                    none of and `local_address`, `remote_address` and `reuse_port` should be specified.

        Backend Parameters:
            backend: the backend to use. Automatically determined otherwise.
            backend_kwargs: Keyword arguments for backend instanciation.
                            Ignored if `backend` is already an :class:`.AsyncBackend` instance.
        """
        super().__init__()
        backend = AsyncBackendFactory.ensure(backend, backend_kwargs)

        if not isinstance(protocol, DatagramProtocol):
            raise TypeError(f"Expected a DatagramProtocol object, got {protocol!r}")

        self.__protocol: DatagramProtocol[_SentPacketT, _ReceivedPacketT] = protocol
        self.__socket: AsyncDatagramSocketAdapter | None = None
        self.__backend: AsyncBackend = backend
        self.__info: _EndpointInfo | None = None

        socket_factory: Callable[[], Awaitable[AsyncDatagramSocketAdapter]]
        match kwargs:
            case {"socket": _socket.socket() as socket, **kwargs}:
                _check_socket_family(socket.family)
                _check_socket_no_ssl(socket)
                _ensure_datagram_socket_bound(socket)
                socket_factory = _make_callback(backend.wrap_udp_socket, socket, **kwargs)
            case _:
                if kwargs.get("local_address") is None:
                    kwargs["local_address"] = ("localhost", 0)
                socket_factory = _make_callback(backend.create_udp_endpoint, **kwargs)

        self.__socket_connector: _SocketConnector | None = _SocketConnector(
            lock=self.__backend.create_lock(),
            factory=_make_callback(self.__create_socket, socket_factory),
            scope=self.__backend.open_cancel_scope(),
        )
        self.__receive_lock: ILock = backend.create_lock()
        self.__send_lock: ILock = backend.create_lock()

    def __repr__(self) -> str:
        try:
            socket = self.__socket
        except AttributeError:
            return f"<{type(self).__name__} (partially initialized)>"
        return f"<{type(self).__name__} socket={socket!r}>"

    async def __aenter__(self) -> Self:
        """
        Calls :meth:`wait_bound`.
        """
        await self.wait_bound()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """
        Calls :meth:`aclose`.
        """
        await self.aclose()

    def __getstate__(self) -> Any:  # pragma: no cover
        raise TypeError(f"cannot pickle {self.__class__.__name__!r} object")

    def is_bound(self) -> bool:
        """
        Checks if the endpoint initialization is finished.

        See Also:
            :meth:`wait_bound` method.

        Returns:
            the endpoint connection state.
        """
        return self.__socket is not None and self.__info is not None

    async def wait_bound(self) -> None:
        """
        Finishes initializing the endpoint, doing the asynchronous operations that could not be done in the constructor.

        It is not needed to call it directly if the endpoint is used as an :term:`asynchronous context manager`::

            async with endpoint:  # wait_bound() has been called.
                ...

        Can be safely called multiple times.

        Warning:
            In the case of a cancellation, this would leave the endpoint in an inconsistent state.

            It is recommended to close the endpoint in this case.

        Raises:
            ClientClosedError: the client object is closed.
            OSError: unrelated OS error occurred. You should check :attr:`OSError.errno`.
        """
        await self.__ensure_opened()

    @staticmethod
    async def __create_socket(
        socket_factory: Callable[[], Awaitable[AsyncDatagramSocketAdapter]],
    ) -> tuple[AsyncDatagramSocketAdapter, _EndpointInfo]:
        socket = await socket_factory()
        socket_proxy = SocketProxy(socket.socket())
        local_address: SocketAddress = new_socket_address(socket_proxy.getsockname(), socket_proxy.family)
        if local_address.port == 0:
            raise AssertionError(f"{socket} is not bound to a local address")
        remote_address: SocketAddress | None
        try:
            remote_address = new_socket_address(socket_proxy.getpeername(), socket_proxy.family)
        except OSError:
            remote_address = None
        info = _EndpointInfo(
            proxy=socket_proxy,
            local_address=local_address,
            remote_address=remote_address,
        )
        return socket, info

    def is_closing(self) -> bool:
        """
        Checks if the endpoint is closed or in the process of being closed.

        If :data:`True`, all future operations on the endpoint object will raise a :exc:`.ClientClosedError`.

        See Also:
            :meth:`aclose` method.

        Returns:
            the endpoint state.
        """
        if self.__socket_connector is not None:
            return False
        socket = self.__socket
        return socket is None or socket.is_closing()

    async def aclose(self) -> None:
        """
        Close the endpoint.

        Once that happens, all future operations on the endpoint object will raise a :exc:`.ClientClosedError`.

        Warning:
            :meth:`aclose` performs a graceful close, waiting for the connection to close.

            If :meth:`aclose` is cancelled, the client is closed abruptly.

        Can be safely called multiple times.
        """
        if self.__socket_connector is not None:
            self.__socket_connector.scope.cancel()
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

    async def send_packet_to(
        self,
        packet: _SentPacketT,
        address: tuple[str, int] | tuple[str, int, int, int] | None,
    ) -> None:
        """
        Sends `packet` to the remote endpoint `address`. Does not require task synchronization.

        If a remote address is configured, `address` must be :data:`None` or the same as the remote address,
        otherwise `address` must not be :data:`None`.

        Warning:
            In the case of a cancellation, it is impossible to know if all the packet data has been sent.

        Parameters:
            packet: the Python object to send.

        Raises:
            ClientClosedError: the endpoint object is closed.
            OSError: unrelated OS error occurred. You should check :attr:`OSError.errno`.
            ValueError: Invalid `address` value.
        """
        async with self.__send_lock:
            socket = await self.__ensure_opened()
            assert self.__info is not None  # nosec assert_used
            if (remote_addr := self.__info.remote_address) is not None:
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
        """
        Waits for a new packet to arrive from another endpoint. Does not require task synchronization.

        Raises:
            ClientClosedError: the endpoint object is closed.
            OSError: unrelated OS error occurred. You should check :attr:`OSError.errno`.
            DatagramProtocolParseError: invalid data received.

        Returns:
            A ``(packet, address)`` tuple, where `address` is the endpoint that delivered this packet.
        """
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

    async def iter_received_packets_from(
        self,
        *,
        timeout: float | None = 0,
    ) -> AsyncGenerator[tuple[_ReceivedPacketT, SocketAddress], None]:
        """
        Returns an :term:`asynchronous iterator` that waits for a new packet to arrive from another endpoint.

        If `timeout` is not :data:`None`, the entire receive operation will take at most `timeout` seconds; it defaults to zero.

        Important:
            The `timeout` is for the entire iterator::

                async_iterator = endpoint.iter_received_packets_from(timeout=10)

                # Let's say that this call took 6 seconds...
                first_packet = await anext(async_iterator)

                # ...then this call has a maximum of 4 seconds, not 10.
                second_packet = await anext(async_iterator)

            The time taken outside the iterator object is not decremented to the timeout parameter.

        Parameters:
            timeout: the allowed time (in seconds) for all the receive operations.

        Yields:
            A ``(packet, address)`` tuple, where `address` is the endpoint that delivered this packet.
        """

        if timeout is None:
            timeout = math.inf

        perf_counter = time.perf_counter
        timeout_after = self.get_backend().timeout

        while True:
            try:
                with timeout_after(timeout):
                    _start = perf_counter()
                    packet_tuple = await self.recv_packet_from()
                    _end = perf_counter()
            except OSError:
                return
            yield packet_tuple
            timeout -= _end - _start
            timeout = max(timeout, 0)

    def get_local_address(self) -> SocketAddress:
        """
        Returns the local socket IP address.

        Raises:
            ClientClosedError: the endpoint object is closed.
            OSError: unrelated OS error occurred. You should check :attr:`OSError.errno`.

        Returns:
            the endpoint's local address.
        """
        if self.__info is None:
            raise _error_from_errno(_errno.ENOTSOCK)
        return self.__info.local_address

    def get_remote_address(self) -> SocketAddress | None:
        """
        Returns the remote socket IP address.

        Raises:
            ClientClosedError: the endpoint object is closed.
            OSError: unrelated OS error occurred. You should check :attr:`OSError.errno`.

        Returns:
            the endpoint's remote address if configured, :data:`None` otherwise.
        """
        if self.__info is None:
            raise _error_from_errno(_errno.ENOTSOCK)
        return self.__info.remote_address

    def get_backend(self) -> AsyncBackend:
        return self.__backend

    async def __ensure_opened(self) -> AsyncDatagramSocketAdapter:
        if self.__socket is None or self.__info is None:
            socket_and_info = None
            if (socket_connector := self.__socket_connector) is not None:
                socket_and_info = await socket_connector.get()
            self.__socket_connector = None
            if socket_and_info is None:
                raise ClientClosedError("Client is closing, or is already closed")
            self.__socket, self.__info = socket_and_info
        if self.__socket.is_closing():
            raise _error_from_errno(_errno.ECONNABORTED)
        return self.__socket

    @property
    @final
    def socket(self) -> SocketProxy:
        """A view to the underlying socket instance. Read-only attribute.

        May raise :exc:`AttributeError` if :meth:`wait_bound` was not called.
        """
        if self.__info is None:
            raise AttributeError("Socket not connected")
        return self.__info.proxy


class AsyncUDPNetworkClient(AbstractAsyncNetworkClient[_SentPacketT, _ReceivedPacketT], Generic[_SentPacketT, _ReceivedPacketT]):
    """
    An asynchronous network client interface for UDP communication.
    """

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
        backend: str | AsyncBackend | None = ...,
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
        backend: str | AsyncBackend | None = ...,
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
        """
        Common Parameters:
            protocol: The :term:`protocol object` to use.

        Connection Parameters:
            address: A pair of ``(host, port)`` for connection.
            local_address: If given, is a ``(local_host, local_port)`` tuple used to bind the socket locally.
            reuse_port: Tells the kernel to allow this endpoint to be bound to the same port as other existing
                        endpoints are bound to, so long as they all set this flag when being created.
                        This option is not supported on Windows and some Unixes.
                        If the SO_REUSEPORT constant is not defined then this capability is unsupported.

        Socket Parameters:
            socket: An already connected UDP :class:`socket.socket`. If `socket` is given,
                    none of and `local_address` and `reuse_port` should be specified.

        Backend Parameters:
            backend: the backend to use. Automatically determined otherwise.
            backend_kwargs: Keyword arguments for backend instanciation.
                            Ignored if `backend` is already an :class:`.AsyncBackend` instance.
        """
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
        """
        Checks if the client initialization is finished.

        See Also:
            :meth:`wait_connected` method.

        Returns:
            the client connection state.
        """
        return self.__endpoint.is_bound() and self.__endpoint.get_remote_address() is not None

    async def wait_connected(self) -> None:
        """
        Finishes initializing the client, doing the asynchronous operations that could not be done in the constructor.
        Does not require task synchronization.

        It is not needed to call it directly if the client is used as an :term:`asynchronous context manager`::

            async with client:  # wait_connected() has been called.
                ...

        Can be safely called multiple times.

        Raises:
            ClientClosedError: the client object is closed.
            OSError: unrelated OS error occurred. You should check :attr:`OSError.errno`.
        """
        await self.__endpoint.wait_bound()
        self.__check_remote_address()

    def is_closing(self) -> bool:
        """
        Checks if the client is closed or in the process of being closed.

        If :data:`True`, all future operations on the client object will raise a :exc:`.ClientClosedError`.

        See Also:
            :meth:`aclose` method.

        Returns:
            the client state.
        """
        return self.__endpoint.is_closing()

    async def aclose(self) -> None:
        """
        Close the client. Does not require task synchronization.

        Once that happens, all future operations on the client object will raise a :exc:`.ClientClosedError`.
        The remote end will receive no more data (after queued data is flushed).

        Warning:
            :meth:`aclose` performs a graceful close, waiting for the connection to close.

            If :meth:`aclose` is cancelled, the client is closed abruptly.

        Can be safely called multiple times.
        """
        return await self.__endpoint.aclose()

    async def send_packet(self, packet: _SentPacketT) -> None:
        """
        Sends `packet` to the remote endpoint. Does not require task synchronization.

        Warning:
            In the case of a cancellation, it is impossible to know if all the packet data has been sent.

        Parameters:
            packet: the Python object to send.

        Raises:
            ClientClosedError: the client object is closed.
            OSError: unrelated OS error occurred. You should check :attr:`OSError.errno`.
        """
        return await self.__endpoint.send_packet_to(packet, None)

    async def recv_packet(self) -> _ReceivedPacketT:
        """
        Waits for a new packet to arrive from the remote endpoint. Does not require task synchronization.

        Calls :meth:`wait_connected`.

        Raises:
            ClientClosedError: the client object is closed.
            OSError: unrelated OS error occurred. You should check :attr:`OSError.errno`.
            DatagramProtocolParseError: invalid data received.

        Returns:
            the received packet.
        """
        packet, _ = await self.__endpoint.recv_packet_from()
        return packet

    async def iter_received_packets(self, *, timeout: float | None = 0) -> AsyncGenerator[_ReceivedPacketT, None]:
        async with contextlib.aclosing(self.__endpoint.iter_received_packets_from(timeout=timeout)) as generator:
            async for packet, _ in generator:
                yield packet

    iter_received_packets.__doc__ = AbstractAsyncNetworkClient.iter_received_packets.__doc__

    def get_local_address(self) -> SocketAddress:
        """
        Returns the local socket IP address.

        Raises:
            ClientClosedError: the client object is closed.
            OSError: unrelated OS error occurred. You should check :attr:`OSError.errno`.

        Returns:
            the client's local address.
        """
        return self.__endpoint.get_local_address()

    def get_remote_address(self) -> SocketAddress:
        """
        Returns the remote socket IP address.

        Raises:
            ClientClosedError: the client object is closed.
            OSError: unrelated OS error occurred. You should check :attr:`OSError.errno`.

        Returns:
            the client's remote address.
        """
        remote_address: SocketAddress = self.__check_remote_address()
        return remote_address

    def get_backend(self) -> AsyncBackend:
        return self.__endpoint.get_backend()

    get_backend.__doc__ = AbstractAsyncNetworkClient.get_backend.__doc__

    def __check_remote_address(self) -> SocketAddress:
        remote_address: SocketAddress | None = self.__endpoint.get_remote_address()
        if remote_address is None:
            raise OSError("No remote address configured") from _error_from_errno(_errno.ENOTCONN)
        return remote_address

    @property
    @final
    def socket(self) -> SocketProxy:
        """A view to the underlying socket instance. Read-only attribute.

        May raise :exc:`AttributeError` if :meth:`wait_connected` was not called.
        """
        return self.__endpoint.socket
