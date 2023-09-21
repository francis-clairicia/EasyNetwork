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

__all__ = ["AsyncTCPNetworkClient"]

import contextlib as _contextlib
import errno as _errno
import socket as _socket
from collections.abc import Callable, Iterator, Mapping
from typing import TYPE_CHECKING, Any, NoReturn, TypedDict, final, overload

try:
    import ssl as _ssl
except ImportError:  # pragma: no cover
    _ssl_module = None
else:
    _ssl_module = _ssl
    del _ssl

from ..._typevars import _ReceivedPacketT, _SentPacketT
from ...exceptions import ClientClosedError
from ...protocol import StreamProtocol
from ...tools._stream import StreamDataConsumer
from ...tools._utils import (
    check_real_socket_state as _check_real_socket_state,
    check_socket_family as _check_socket_family,
    check_socket_no_ssl as _check_socket_no_ssl,
    error_from_errno as _error_from_errno,
)
from ...tools.constants import CLOSED_SOCKET_ERRNOS, MAX_STREAM_BUFSIZE, SSL_HANDSHAKE_TIMEOUT, SSL_SHUTDOWN_TIMEOUT
from ...tools.socket import SocketAddress, SocketProxy, new_socket_address, set_tcp_keepalive, set_tcp_nodelay
from ..backend.abc import AsyncBackend, AsyncStreamSocketAdapter, ILock
from ..backend.factory import AsyncBackendFactory
from ..backend.tasks import SingleTaskRunner
from .abc import AbstractAsyncNetworkClient

if TYPE_CHECKING:
    import ssl as _typing_ssl


class _ClientInfo(TypedDict):
    proxy: SocketProxy
    local_address: SocketAddress
    remote_address: SocketAddress


class AsyncTCPNetworkClient(AbstractAsyncNetworkClient[_SentPacketT, _ReceivedPacketT]):
    """
    An asynchronous network client interface for TCP connections.
    """

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
        "__eof_sent",
        "__max_recv_size",
    )

    @overload
    def __init__(
        self,
        address: tuple[str, int],
        /,
        protocol: StreamProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        local_address: tuple[str, int] | None = ...,
        happy_eyeballs_delay: float | None = ...,
        ssl: _typing_ssl.SSLContext | bool | None = ...,
        server_hostname: str | None = ...,
        ssl_handshake_timeout: float | None = ...,
        ssl_shutdown_timeout: float | None = ...,
        ssl_shared_lock: bool | None = ...,
        max_recv_size: int | None = ...,
        backend: str | AsyncBackend | None = ...,
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
        ssl: _typing_ssl.SSLContext | bool | None = ...,
        server_hostname: str | None = ...,
        ssl_handshake_timeout: float | None = ...,
        ssl_shutdown_timeout: float | None = ...,
        ssl_shared_lock: bool | None = ...,
        max_recv_size: int | None = ...,
        backend: str | AsyncBackend | None = ...,
        backend_kwargs: Mapping[str, Any] | None = ...,
    ) -> None:
        ...

    def __init__(
        self,
        __arg: tuple[str, int] | _socket.socket,
        /,
        protocol: StreamProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        ssl: _typing_ssl.SSLContext | bool | None = None,
        server_hostname: str | None = None,
        ssl_handshake_timeout: float | None = None,
        ssl_shutdown_timeout: float | None = None,
        ssl_shared_lock: bool | None = None,
        max_recv_size: int | None = None,
        backend: str | AsyncBackend | None = None,
        backend_kwargs: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Common Parameters:
            protocol: The :term:`protocol object` to use.

        Connection Parameters:
            address: A pair of ``(host, port)`` for connection.
            happy_eyeballs_delay: the "Connection Attempt Delay" as defined in :rfc:`8305`.
                                  A sensible default value recommended by the RFC is 0.25 (250 milliseconds).
            local_address: If given, is a ``(local_host, local_port)`` tuple used to bind the socket locally.

        Socket Parameters:
            socket: An already connected TCP :class:`socket.socket`. If `socket` is given,
                    none of `happy_eyeballs_delay` and `local_address` should be specified.

        Keyword Arguments:
            ssl: If given and not false, a SSL/TLS transport is created (by default a plain TCP transport is created).
                 If ssl is a :class:`ssl.SSLContext` object, this context is used to create the transport;
                 if ssl is :data:`True`, a default context returned from :func:`ssl.create_default_context` is used.
            server_hostname: sets or overrides the hostname that the target server's certificate will be matched against.
                             Should only be passed if `ssl` is not :data:`None`. By default the value of the host in `address`
                             argument is used. If `socket` is provided instead, there is no default and you must pass a value
                             for `server_hostname`. If `server_hostname` is an empty string, hostname matching is disabled
                             (which is a serious security risk, allowing for potential man-in-the-middle attacks).
            ssl_handshake_timeout: (for a TLS connection) the time in seconds to wait for the TLS handshake to complete
                                   before aborting the connection. ``60.0`` seconds if :data:`None` (default).
            ssl_shutdown_timeout: the time in seconds to wait for the SSL shutdown to complete before aborting the connection.
                                  ``30.0`` seconds if :data:`None` (default).
            ssl_shared_lock: If :data:`True` (the default), :meth:`send_packet` and :meth:`recv_packet` uses
                             the same lock instance.
            max_recv_size: Read buffer size. If not given, a default reasonable value is used.

        Backend Parameters:
            backend: the backend to use. Automatically determined otherwise.
            backend_kwargs: Keyword arguments for backend instanciation.
                            Ignored if `backend` is already an :class:`.AsyncBackend` instance.

        See Also:
            :ref:`SSL/TLS security considerations <ssl-security>`
        """
        super().__init__()

        if not isinstance(protocol, StreamProtocol):
            raise TypeError(f"Expected a StreamProtocol object, got {protocol!r}")
        self.__consumer: StreamDataConsumer[_ReceivedPacketT] = StreamDataConsumer(protocol)
        self.__producer: Callable[[_SentPacketT], Iterator[bytes]] = protocol.generate_chunks

        backend = AsyncBackendFactory.ensure(backend, backend_kwargs)
        if max_recv_size is None:
            max_recv_size = MAX_STREAM_BUFSIZE
        if not isinstance(max_recv_size, int) or max_recv_size <= 0:
            raise ValueError("'max_recv_size' must be a strictly positive integer")

        self.__socket: AsyncStreamSocketAdapter | None = None
        self.__backend: AsyncBackend = backend
        self.__info: _ClientInfo | None = None

        if ssl:
            if _ssl_module is None:
                raise RuntimeError("stdlib ssl module not available")
            if isinstance(ssl, bool):
                ssl = _ssl_module.create_default_context()
                assert isinstance(ssl, _ssl_module.SSLContext)  # nosec assert_used
                if server_hostname is not None and not server_hostname:
                    ssl.check_hostname = False
        else:
            if server_hostname is not None:
                raise ValueError("server_hostname is only meaningful with ssl")

            if ssl_handshake_timeout is not None:
                raise ValueError("ssl_handshake_timeout is only meaningful with ssl")

            if ssl_shutdown_timeout is not None:
                raise ValueError("ssl_shutdown_timeout is only meaningful with ssl")

            if ssl_shared_lock is not None:
                raise ValueError("ssl_shared_lock is only meaningful with ssl")

        if ssl_shared_lock is None:
            ssl_shared_lock = True

        def _value_or_default(value: float | None, default: float) -> float:
            return value if value is not None else default

        self.__socket_connector: SingleTaskRunner[AsyncStreamSocketAdapter] | None = None
        match __arg:
            case _socket.socket() as socket:
                _check_socket_family(socket.family)
                _check_socket_no_ssl(socket)
                if ssl:
                    if server_hostname is None:
                        raise ValueError("You must set server_hostname when using ssl without a host")
                    self.__socket_connector = SingleTaskRunner(
                        backend,
                        backend.wrap_ssl_over_tcp_client_socket,
                        socket,
                        ssl_context=ssl,
                        server_hostname=server_hostname,
                        ssl_handshake_timeout=_value_or_default(ssl_handshake_timeout, SSL_HANDSHAKE_TIMEOUT),
                        ssl_shutdown_timeout=_value_or_default(ssl_shutdown_timeout, SSL_SHUTDOWN_TIMEOUT),
                        **kwargs,
                    )
                else:
                    self.__socket_connector = SingleTaskRunner(backend, backend.wrap_tcp_client_socket, socket, **kwargs)
            case (host, port):
                if ssl:
                    self.__socket_connector = SingleTaskRunner(
                        backend,
                        backend.create_ssl_over_tcp_connection,
                        host,
                        port,
                        ssl_context=ssl,
                        server_hostname=server_hostname,
                        ssl_handshake_timeout=_value_or_default(ssl_handshake_timeout, SSL_HANDSHAKE_TIMEOUT),
                        ssl_shutdown_timeout=_value_or_default(ssl_shutdown_timeout, SSL_SHUTDOWN_TIMEOUT),
                        **kwargs,
                    )
                else:
                    self.__socket_connector = SingleTaskRunner(backend, backend.create_tcp_connection, host, port, **kwargs)
            case _:  # pragma: no cover
                raise TypeError("Invalid arguments")

        assert self.__socket_connector is not None  # nosec assert_used
        assert ssl_shared_lock is not None  # nosec assert_used

        self.__receive_lock: ILock
        self.__send_lock: ILock
        if ssl and ssl_shared_lock:
            self.__send_lock = self.__receive_lock = backend.create_lock()
        else:
            self.__receive_lock = backend.create_lock()
            self.__send_lock = backend.create_lock()
        self.__eof_reached: bool = False
        self.__eof_sent: bool = False
        self.__max_recv_size: int = max_recv_size

    def __repr__(self) -> str:
        try:
            socket = self.__socket
        except AttributeError:
            return f"<{type(self).__name__} (partially initialized)>"
        return f"<{type(self).__name__} socket={socket!r}>"

    def is_connected(self) -> bool:
        """
        Checks if the client initialization is finished.

        See Also:
            :meth:`wait_connected` method.

        Returns:
            the client connection state.
        """
        return self.__socket is not None and self.__info is not None

    async def wait_connected(self) -> None:
        """
        Finishes initializing the client, doing the asynchronous operations that could not be done in the constructor.
        Does not require task synchronization.

        It is not needed to call it directly if the client is used as an :term:`asynchronous context manager`::

            async with client:  # wait_connected() has been called.
                ...

        Can be safely called multiple times.

        Warning:
            Due to limitations of the underlying operating system APIs,
            it is not always possible to properly cancel a connection attempt once it has begun.

            If :meth:`wait_connected` is cancelled, and is unable to abort the connection attempt, then it will forcibly
            close the socket to prevent accidental re-use.

        Raises:
            ClientClosedError: the client object is closed.
            ConnectionError: could not connect to remote.
            OSError: unrelated OS error occurred. You should check :attr:`OSError.errno`.
        """
        if self.__socket is None:
            socket_connector = self.__socket_connector
            if socket_connector is None:
                raise ClientClosedError("Client is closing, or is already closed")
            socket = await socket_connector.run()
            if self.__socket_connector is None:  # wait_connected() or aclose() called in concurrency
                return await self.__backend.cancel_shielded_coro_yield()
            self.__socket = socket
            self.__socket_connector = None
        if self.__info is None:
            self.__info = self.__build_info_dict(self.__socket)
            socket_proxy = self.__info["proxy"]
            with _contextlib.suppress(OSError):
                set_tcp_nodelay(socket_proxy, True)
            with _contextlib.suppress(OSError):
                set_tcp_keepalive(socket_proxy, True)

    @staticmethod
    def __build_info_dict(socket: AsyncStreamSocketAdapter) -> _ClientInfo:
        socket_proxy = SocketProxy(socket.socket())
        local_address: SocketAddress = new_socket_address(socket_proxy.getsockname(), socket_proxy.family)
        remote_address: SocketAddress = new_socket_address(socket_proxy.getpeername(), socket_proxy.family)
        return {
            "proxy": socket_proxy,
            "local_address": local_address,
            "remote_address": remote_address,
        }

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
        socket = self.__socket
        return socket is None or socket.is_closing()

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
            self.__socket_connector.cancel()
            self.__socket_connector = None
        async with self.__send_lock:
            socket, self.__socket = self.__socket, None
            if socket is None:
                return
            try:
                await socket.aclose()
            except (ConnectionError, TimeoutError):
                # It is normal if there was connection errors during operations. But do not propagate this exception,
                # as we will never reuse this socket
                pass

    async def send_packet(self, packet: _SentPacketT) -> None:
        """
        Sends `packet` to the remote endpoint. Does not require task synchronization.

        Calls :meth:`wait_connected`.

        Warning:
            In the case of a cancellation, it is impossible to know if all the packet data has been sent.
            This would leave the connection in an inconsistent state.

        Parameters:
            packet: the Python object to send.

        Raises:
            ClientClosedError: the client object is closed.
            ConnectionError: connection unexpectedly closed during operation.
                             You should not attempt any further operation and close the client object.
            OSError: unrelated OS error occurred. You should check :attr:`OSError.errno`.
            RuntimeError: :meth:`send_eof` has been called earlier.
        """
        async with self.__send_lock:
            socket = await self.__ensure_connected()
            if self.__eof_sent:
                raise RuntimeError("send_eof() has been called earlier")
            with self.__convert_socket_error():
                await socket.sendall_fromiter(filter(None, self.__producer(packet)))
                _check_real_socket_state(self.socket)

    async def send_eof(self) -> None:
        """
        Close the write end of the stream after the buffered write data is flushed. Does not require task synchronization.

        Can be safely called multiple times.

        Raises:
            ClientClosedError: the client object is closed.
            OSError: unrelated OS error occurred. You should check :attr:`OSError.errno`.
        """
        async with self.__send_lock:
            if self.__eof_sent:
                return
            try:
                socket = await self.__ensure_connected()
            except ConnectionError:
                return
            await socket.send_eof()
            self.__eof_sent = True

    async def recv_packet(self) -> _ReceivedPacketT:
        """
        Waits for a new packet to arrive from the remote endpoint. Does not require task synchronization.

        Calls :meth:`wait_connected`.

        Raises:
            ClientClosedError: the client object is closed.
            ConnectionError: connection unexpectedly closed during operation.
                             You should not attempt any further operation and close the client object.
            OSError: unrelated OS error occurred. You should check :attr:`OSError.errno`.
            StreamProtocolParseError: invalid data received.

        Returns:
            the received packet.
        """
        async with self.__receive_lock:
            consumer = self.__consumer
            try:
                return next(consumer)  # If there is enough data from last call to create a packet, return immediately
            except StopIteration:
                pass

            socket = await self.__ensure_connected()
            if self.__eof_reached:
                self.__abort(None)

            bufsize: int = self.__max_recv_size

            while True:
                with self.__convert_socket_error():
                    chunk: bytes = await socket.recv(bufsize)
                try:
                    if not chunk:
                        self.__eof_reached = True
                        self.__abort(None)
                    consumer.feed(chunk)
                finally:
                    del chunk
                try:
                    return next(consumer)
                except StopIteration:
                    pass

    def get_local_address(self) -> SocketAddress:
        """
        Returns the local socket IP address.

        If :meth:`wait_connected` was not called, an :exc:`OSError` may occurr.

        Raises:
            ClientClosedError: the client object is closed.
            OSError: unrelated OS error occurred. You should check :attr:`OSError.errno`.

        Returns:
            the client's local address.
        """
        if self.__info is None:
            raise _error_from_errno(_errno.ENOTSOCK)
        return self.__info["local_address"]

    def get_remote_address(self) -> SocketAddress:
        """
        Returns the remote socket IP address.

        If :meth:`wait_connected` was not called, an :exc:`OSError` may occurr.

        Raises:
            ClientClosedError: the client object is closed.
            OSError: unrelated OS error occurred. You should check :attr:`OSError.errno`.

        Returns:
            the client's remote address.
        """
        if self.__info is None:
            raise _error_from_errno(_errno.ENOTSOCK)
        return self.__info["remote_address"]

    def get_backend(self) -> AsyncBackend:
        return self.__backend

    get_backend.__doc__ = AbstractAsyncNetworkClient.get_backend.__doc__

    async def __ensure_connected(self) -> AsyncStreamSocketAdapter:
        await self.wait_connected()
        assert self.__socket is not None  # nosec assert_used
        socket = self.__socket
        if socket.is_closing():
            self.__abort(None)
        return socket

    @_contextlib.contextmanager
    def __convert_socket_error(self) -> Iterator[None]:
        try:
            yield
        except ConnectionError as exc:
            self.__abort(exc)
        except OSError as exc:
            if exc.errno in CLOSED_SOCKET_ERRNOS:
                self.__abort(exc)
            raise

    @staticmethod
    def __abort(cause: BaseException | None) -> NoReturn:
        if cause is None:
            raise _error_from_errno(_errno.ECONNABORTED)
        raise _error_from_errno(_errno.ECONNABORTED) from cause

    @property
    @final
    def socket(self) -> SocketProxy:
        """A view to the underlying socket instance. Read-only attribute.

        May raise :exc:`AttributeError` if :meth:`wait_connected` was not called.
        """
        if self.__info is None:
            raise AttributeError("Socket not connected")
        return self.__info["proxy"]

    @property
    @final
    def max_recv_size(self) -> int:
        """Read buffer size. Read-only attribute."""
        return self.__max_recv_size
