# Copyright 2021-2024, Francis Clairicia-Rose-Claire-Josephine
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
"""Asynchronous UDP Network client implementation module."""

from __future__ import annotations

__all__ = ["AsyncUDPNetworkClient"]

import contextlib
import dataclasses as _dataclasses
import errno as _errno
import socket as _socket
import warnings
from collections.abc import Awaitable, Callable, Iterator
from typing import Any, final, overload

from .._typevars import _T_ReceivedPacket, _T_SentPacket
from ..exceptions import ClientClosedError
from ..lowlevel import _utils, constants
from ..lowlevel.api_async.backend.abc import AsyncBackend, CancelScope, ILock
from ..lowlevel.api_async.backend.utils import BuiltinAsyncBackendLiteral, ensure_backend
from ..lowlevel.api_async.endpoints.datagram import AsyncDatagramEndpoint
from ..lowlevel.api_async.transports.abc import AsyncDatagramTransport
from ..lowlevel.socket import INETSocketAttribute, SocketAddress, SocketProxy, new_socket_address
from ..protocol import DatagramProtocol
from .abc import AbstractAsyncNetworkClient


@_dataclasses.dataclass(kw_only=True, slots=True)
class _SocketConnector:
    factory: Callable[[], Awaitable[tuple[AsyncDatagramTransport, SocketProxy]]]
    scope: CancelScope

    async def get(self) -> tuple[AsyncDatagramTransport, SocketProxy] | None:
        result: tuple[AsyncDatagramTransport, SocketProxy] | None = None
        with self.scope:
            result = await self.factory()
        return result


class AsyncUDPNetworkClient(AbstractAsyncNetworkClient[_T_SentPacket, _T_ReceivedPacket]):
    """
    An asynchronous network client interface for UDP communication.
    """

    __slots__ = (
        "__backend",
        "__endpoint",
        "__socket_proxy",
        "__socket_connector",
        "__socket_connector_lock",
        "__receive_lock",
        "__send_lock",
        "__protocol",
    )

    @overload
    def __init__(
        self,
        address: tuple[str, int],
        /,
        protocol: DatagramProtocol[_T_SentPacket, _T_ReceivedPacket],
        backend: AsyncBackend | BuiltinAsyncBackendLiteral | None = ...,
        *,
        local_address: tuple[str, int] | None = ...,
        family: int = ...,
    ) -> None: ...

    @overload
    def __init__(
        self,
        socket: _socket.socket,
        /,
        protocol: DatagramProtocol[_T_SentPacket, _T_ReceivedPacket],
        backend: AsyncBackend | BuiltinAsyncBackendLiteral | None = ...,
    ) -> None: ...

    def __init__(
        self,
        __arg: tuple[str, int] | _socket.socket,
        /,
        protocol: DatagramProtocol[_T_SentPacket, _T_ReceivedPacket],
        backend: AsyncBackend | BuiltinAsyncBackendLiteral | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Common Parameters:
            protocol: The :term:`protocol object` to use.
            backend: The :term:`asynchronous backend interface` to use.

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
        """
        super().__init__()

        if not isinstance(protocol, DatagramProtocol):
            raise TypeError(f"Expected a DatagramProtocol object, got {protocol!r}")

        backend = ensure_backend(backend)

        self.__backend: AsyncBackend = backend
        self.__protocol: DatagramProtocol[_T_SentPacket, _T_ReceivedPacket] = protocol
        self.__endpoint: AsyncDatagramEndpoint[_T_SentPacket, _T_ReceivedPacket] | None = None
        self.__socket_proxy: SocketProxy | None = None

        socket_factory: Callable[[], Awaitable[AsyncDatagramTransport]]
        match __arg:
            case _socket.socket() as socket:
                _utils.check_socket_no_ssl(socket)
                _utils.check_socket_family(socket.family)
                _utils.check_socket_is_connected(socket)
                _utils.ensure_datagram_socket_bound(socket)
                socket_factory = _utils.make_callback(backend.wrap_connected_datagram_socket, socket, **kwargs)
            case (str(host), int(port)):
                if kwargs.get("local_address") is None:
                    kwargs["local_address"] = ("localhost", 0)
                if (family := kwargs.get("family", _socket.AF_UNSPEC)) != _socket.AF_UNSPEC:
                    _utils.check_socket_family(family)
                socket_factory = _utils.make_callback(backend.create_udp_endpoint, host, port, **kwargs)
            case _:
                raise TypeError("Invalid arguments")

        self.__socket_connector: _SocketConnector | None = _SocketConnector(
            factory=_utils.make_callback(self.__create_socket, socket_factory),
            scope=backend.open_cancel_scope(),
        )
        self.__socket_connector_lock: ILock = backend.create_lock()
        self.__receive_lock: ILock = backend.create_lock()
        self.__send_lock: ILock = backend.create_lock()

    @staticmethod
    async def __create_socket(
        socket_factory: Callable[[], Awaitable[AsyncDatagramTransport]],
    ) -> tuple[AsyncDatagramTransport, SocketProxy]:
        transport = await socket_factory()
        socket_proxy = SocketProxy(transport.extra(INETSocketAttribute.socket))

        local_address: SocketAddress = new_socket_address(transport.extra(INETSocketAttribute.sockname), socket_proxy.family)
        if local_address.port == 0:
            raise AssertionError(f"{transport} is not bound to a local address")
        return transport, socket_proxy

    def __del__(self, *, _warn: _utils.WarnCallback = warnings.warn) -> None:
        try:
            endpoint = self.__endpoint
        except AttributeError:
            return
        if endpoint is not None and not endpoint.is_closing():
            msg = f"unclosed client {self!r} pointing to {endpoint!r} (and cannot be closed synchronously)"
            _warn(msg, ResourceWarning, source=self)

    def __repr__(self) -> str:
        try:
            endpoint = self.__endpoint
        except AttributeError:
            endpoint = None
        if endpoint is None:
            return f"<{type(self).__name__} (partially initialized)>"
        return f"<{type(self).__name__} endpoint={endpoint!r}>"

    def is_connected(self) -> bool:
        """
        Checks if the client initialization is finished.

        See Also:
            :meth:`wait_connected` method.

        Returns:
            the client connection state.
        """
        return self.__endpoint is not None

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
        await self.__ensure_connected()

    def is_closing(self) -> bool:
        """
        Checks if the client is closed or in the process of being closed.

        If :data:`True`, all future operations on the client object will raise a :exc:`.ClientClosedError`.

        See Also:
            :meth:`aclose` method.

        Returns:
            the client state.
        """
        if self.__socket_connector is not None:
            return False
        endpoint = self.__endpoint
        return endpoint is None or endpoint.is_closing()

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
        if self.__socket_connector is not None:
            self.__socket_connector.scope.cancel()
            self.__socket_connector = None
        async with self.__send_lock:
            if self.__endpoint is None:
                return
            await self.__endpoint.aclose()

    async def send_packet(self, packet: _T_SentPacket) -> None:
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
        async with self.__send_lock:
            endpoint = await self.__ensure_connected()
            with self.__convert_socket_error():
                await endpoint.send_packet(packet)
                _utils.check_real_socket_state(endpoint.extra(INETSocketAttribute.socket))

    async def recv_packet(self) -> _T_ReceivedPacket:
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
        async with self.__receive_lock:
            endpoint = await self.__ensure_connected()
            with self.__convert_socket_error():
                return await endpoint.recv_packet()

    def get_local_address(self) -> SocketAddress:
        """
        Returns the local socket IP address.

        Raises:
            ClientClosedError: the client object is closed.
            OSError: unrelated OS error occurred. You should check :attr:`OSError.errno`.

        Returns:
            the client's local address.
        """
        endpoint = self.__get_endpoint_sync()
        local_address = endpoint.extra(INETSocketAttribute.sockname)
        address_family = endpoint.extra(INETSocketAttribute.family)
        return new_socket_address(local_address, address_family)

    def get_remote_address(self) -> SocketAddress:
        """
        Returns the remote socket IP address.

        Raises:
            ClientClosedError: the client object is closed.
            OSError: unrelated OS error occurred. You should check :attr:`OSError.errno`.

        Returns:
            the client's remote address.
        """
        endpoint = self.__get_endpoint_sync()
        remote_address = endpoint.extra(INETSocketAttribute.peername)
        address_family = endpoint.extra(INETSocketAttribute.family)
        return new_socket_address(remote_address, address_family)

    @_utils.inherit_doc(AbstractAsyncNetworkClient)
    def backend(self) -> AsyncBackend:
        return self.__backend

    async def __ensure_connected(self) -> AsyncDatagramEndpoint[_T_SentPacket, _T_ReceivedPacket]:
        async with self.__socket_connector_lock:
            if self.__endpoint is None:
                endpoint_and_proxy = None
                if (socket_connector := self.__socket_connector) is not None:
                    endpoint_and_proxy = await socket_connector.get()
                self.__socket_connector = None
                if endpoint_and_proxy is None:
                    raise self.__closed()
                transport, self.__socket_proxy = endpoint_and_proxy
                self.__endpoint = AsyncDatagramEndpoint(transport, self.__protocol)

            # If you want coverage.py to work properly, keep this "pass" :)
            pass

        if self.__endpoint.is_closing():
            raise self.__closed()
        return self.__endpoint

    def __get_endpoint_sync(self) -> AsyncDatagramEndpoint[_T_SentPacket, _T_ReceivedPacket]:
        if self.__endpoint is None:
            if self.__socket_connector is not None:
                raise _utils.error_from_errno(_errno.ENOTSOCK)
            else:
                raise self.__closed()
        if self.__endpoint.is_closing():
            raise self.__closed()
        return self.__endpoint

    @contextlib.contextmanager
    def __convert_socket_error(self) -> Iterator[None]:
        try:
            yield
        except OSError as exc:
            if exc.errno in constants.CLOSED_SOCKET_ERRNOS:
                raise self.__closed()
            raise

    @staticmethod
    def __closed() -> ClientClosedError:
        return ClientClosedError("Client is closing, or is already closed")

    @property
    @final
    def socket(self) -> SocketProxy:
        """A view to the underlying socket instance. Read-only attribute.

        May raise :exc:`AttributeError` if :meth:`wait_connected` was not called.
        """
        if self.__socket_proxy is None:
            raise AttributeError("Socket not connected")
        return self.__socket_proxy
