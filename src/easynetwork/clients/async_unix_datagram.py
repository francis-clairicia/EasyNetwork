# Copyright 2021-2025, Francis Clairicia-Rose-Claire-Josephine
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
"""Asynchronous Unix datagram client implementation module.

.. versionadded:: 1.1
"""

from __future__ import annotations

__all__ = ["AsyncUnixDatagramClient"]

import contextlib
import os
import socket as _socket
import warnings
from collections.abc import Awaitable, Callable, Iterator
from typing import Any, final, overload

from .._typevars import _T_ReceivedPacket, _T_SentPacket
from ..exceptions import ClientClosedError
from ..lowlevel import _unix_utils, _utils, constants
from ..lowlevel.api_async.backend.abc import AsyncBackend, ILock
from ..lowlevel.api_async.backend.utils import BuiltinAsyncBackendLiteral, ensure_backend
from ..lowlevel.api_async.endpoints.datagram import AsyncDatagramEndpoint
from ..lowlevel.api_async.transports.abc import AsyncDatagramTransport
from ..lowlevel.api_async.transports.utils import aclose_forcefully
from ..lowlevel.socket import SocketProxy, UnixSocketAddress, UNIXSocketAttribute
from ..protocol import DatagramProtocol
from . import _base
from .abc import AbstractAsyncNetworkClient


class AsyncUnixDatagramClient(AbstractAsyncNetworkClient[_T_SentPacket, _T_ReceivedPacket]):
    """
    An asynchronous Unix datagram client.

    .. versionadded:: 1.1
    """

    __slots__ = (
        "__backend",
        "__endpoint",
        "__socket_proxy",
        "__receive_lock",
        "__send_lock",
    )

    @overload
    def __init__(
        self,
        path: str | os.PathLike[str] | bytes | UnixSocketAddress,
        /,
        protocol: DatagramProtocol[_T_SentPacket, _T_ReceivedPacket],
        backend: AsyncBackend | BuiltinAsyncBackendLiteral | None = ...,
        *,
        local_path: str | os.PathLike[str] | bytes | UnixSocketAddress | None = ...,
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
        __arg: str | os.PathLike[str] | bytes | UnixSocketAddress | _socket.socket,
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
            path: Path of the socket.
            local_path: If given, is a Unix socket address used to bind the socket locally.

        Socket Parameters:
            socket: An already connected Unix datagram :class:`socket.socket`. If `socket` is given,
                    `local_address` should not be specified.
        """
        super().__init__()

        if not isinstance(protocol, DatagramProtocol):
            raise TypeError(f"Expected a DatagramProtocol object, got {protocol!r}")

        backend = ensure_backend(backend)

        self.__backend: AsyncBackend = backend
        self.__socket_proxy: SocketProxy | None = None

        socket_factory: Callable[[], Awaitable[AsyncDatagramTransport]]
        match __arg:
            case _socket.socket() as socket:
                try:
                    _utils.check_socket_no_ssl(socket)
                    _unix_utils.check_unix_socket_family(socket.family)
                    _utils.check_socket_is_connected(socket)
                    if not socket.getsockname():
                        raise ValueError(f"{self.__class__.__name__} requires the socket to be named.")
                except BaseException:
                    socket.close()
                    raise
                socket_factory = _utils.make_callback(backend.wrap_connected_datagram_socket, socket, **kwargs)
            case path:
                path = _unix_utils.convert_unix_socket_address(path)
                kwargs["local_path"] = _unix_utils.convert_optional_unix_socket_address(kwargs.get("local_path"))
                if not kwargs["local_path"]:
                    if _unix_utils.platform_supports_automatic_socket_bind():
                        # Explictly set local_path to empty string.
                        # local_path could be None at this point.
                        kwargs["local_path"] = ""
                    else:
                        msg = "local_path parameter is required on this platform and cannot be an empty string."
                        note = "Automatic socket bind is not supported."
                        raise _utils.exception_with_notes(ValueError(msg), note)
                socket_factory = _utils.make_callback(backend.create_unix_datagram_endpoint, path, **kwargs)

        self.__endpoint = _base.DeferredAsyncEndpointInit(
            backend=backend,
            endpoint_factory=_utils.make_callback(
                self.__create_endpoint,
                socket_factory,
                protocol=protocol,
            ),
        )

        self.__receive_lock: ILock = backend.create_lock()
        self.__send_lock: ILock = backend.create_fair_lock()

    @staticmethod
    async def __create_endpoint(
        transport_factory: Callable[[], Awaitable[AsyncDatagramTransport]],
        *,
        protocol: DatagramProtocol[_T_SentPacket, _T_ReceivedPacket],
    ) -> AsyncDatagramEndpoint[_T_SentPacket, _T_ReceivedPacket]:
        transport = await transport_factory()
        socket = transport.extra(UNIXSocketAttribute.socket)
        local_name = UnixSocketAddress.from_raw(socket.getsockname())
        if local_name.is_unnamed():
            raise AssertionError(f"{transport} is unnamed.")
        return AsyncDatagramEndpoint(transport, protocol)

    def __del__(self, *, _warn: _utils.WarnCallback = warnings.warn) -> None:
        try:
            endpoint = self.__endpoint.get_endpoint_unchecked()
        except AttributeError:
            return
        if endpoint is not None and not endpoint.is_closing():
            msg = f"unclosed client {self!r} pointing to {endpoint!r} (and cannot be closed synchronously)"
            _warn(msg, ResourceWarning, source=self)

    def __repr__(self) -> str:
        try:
            endpoint = self.__endpoint.get_endpoint_unchecked()
        except AttributeError:
            endpoint = None
        if endpoint is None:
            return f"<{self.__class__.__name__} (partially initialized)>"
        return f"<{self.__class__.__name__} endpoint={endpoint!r}>"

    def is_connected(self) -> bool:
        """
        Checks if the client initialization is finished.

        See Also:
            :meth:`wait_connected` method.

        Returns:
            the client connection state.
        """
        return self.__endpoint.is_connected()

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
        await self.__endpoint.connect()

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
        Closes the client. Does not require task synchronization.

        Once that happens, all future operations on the client object will raise a :exc:`.ClientClosedError`.
        The remote end will receive no more data (after queued data is flushed).

        Warning:
            :meth:`aclose` performs a graceful close, waiting for the connection to close.

            If :meth:`aclose` is cancelled, the client is closed abruptly.

        Can be safely called multiple times.
        """
        async with contextlib.AsyncExitStack() as stack:
            try:
                await stack.enter_async_context(self.__send_lock)
            except self.backend().get_cancelled_exc_class():
                if not self.__endpoint.is_closing():
                    await aclose_forcefully(self.__endpoint)
                raise
            else:
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
            endpoint = await self.__endpoint.connect()
            with self.__convert_socket_error(endpoint=endpoint):
                await endpoint.send_packet(packet)
                _utils.check_real_socket_state(endpoint.extra(UNIXSocketAttribute.socket))

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
            endpoint = await self.__endpoint.connect()
            with self.__convert_socket_error(endpoint=endpoint):
                return await endpoint.recv_packet()
            raise AssertionError("Expected code to be unreachable.")

    def get_local_name(self) -> UnixSocketAddress:
        """
        Returns the socket name.

        If :meth:`wait_connected` was not called, an :exc:`OSError` may occur.

        Raises:
            ClientClosedError: the client object is closed.
            OSError: unrelated OS error occurred. You should check :attr:`OSError.errno`.

        Returns:
            the client's local name.
        """
        endpoint = self.__endpoint.get_sync()
        sock_name = endpoint.extra(UNIXSocketAttribute.sockname)
        return UnixSocketAddress.from_raw(sock_name)

    def get_peer_name(self) -> UnixSocketAddress:
        """
        Returns the peer socket name.

        If :meth:`wait_connected` was not called, an :exc:`OSError` may occur.

        Raises:
            ClientClosedError: the client object is closed.
            OSError: unrelated OS error occurred. You should check :attr:`OSError.errno`.

        Returns:
            the client's peer name.
        """
        endpoint = self.__endpoint.get_sync()
        peer_name = endpoint.extra(UNIXSocketAttribute.peername)
        return UnixSocketAddress.from_raw(peer_name)

    @_utils.inherit_doc(AbstractAsyncNetworkClient)
    def backend(self) -> AsyncBackend:
        return self.__backend

    @classmethod
    @contextlib.contextmanager
    def __convert_socket_error(cls, *, endpoint: AsyncDatagramEndpoint[Any, Any] | None) -> Iterator[None]:
        try:
            yield
        except OSError as exc:
            if exc.errno in constants.CLOSED_SOCKET_ERRNOS:
                if endpoint is not None and endpoint.is_closing():
                    # aclose() called while recv_packet() is awaiting...
                    raise cls.__closed() from exc
                exc.add_note("The socket file descriptor was closed unexpectedly.")
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
        if (socket_proxy := self.__socket_proxy) is not None:
            return socket_proxy

        try:
            endpoint = self.__endpoint.get_sync()
        except OSError:
            pass
        else:
            self.__socket_proxy = socket_proxy = SocketProxy(endpoint.extra(UNIXSocketAttribute.socket))
            return socket_proxy

        raise AttributeError("Socket not connected")
