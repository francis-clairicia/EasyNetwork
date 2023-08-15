# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Asynchronous network client module"""

from __future__ import annotations

__all__ = ["AsyncTCPNetworkClient"]

import contextlib as _contextlib
import errno as _errno
import socket as _socket
from collections.abc import Callable, Iterator, Mapping
from typing import TYPE_CHECKING, Any, Generic, NoReturn, TypedDict, TypeVar, cast, final, overload

try:
    import ssl as _ssl
except ImportError:  # pragma: no cover
    _ssl_module = None
else:
    _ssl_module = _ssl
    del _ssl

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
from ..backend.abc import (
    AbstractAsyncBackend,
    AbstractAsyncHalfCloseableStreamSocketAdapter,
    AbstractAsyncStreamSocketAdapter,
    ILock,
)
from ..backend.factory import AsyncBackendFactory
from ..backend.tasks import SingleTaskRunner
from .abc import AbstractAsyncNetworkClient

if TYPE_CHECKING:
    from ssl import SSLContext as _SSLContext

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
        ssl: _SSLContext | bool | None = ...,
        server_hostname: str | None = ...,
        ssl_handshake_timeout: float | None = ...,
        ssl_shutdown_timeout: float | None = ...,
        ssl_shared_lock: bool | None = ...,
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
        ssl: _SSLContext | bool | None = ...,
        server_hostname: str | None = ...,
        ssl_handshake_timeout: float | None = ...,
        ssl_shutdown_timeout: float | None = ...,
        ssl_shared_lock: bool | None = ...,
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
        ssl: _SSLContext | bool | None = None,
        server_hostname: str | None = None,
        ssl_handshake_timeout: float | None = None,
        ssl_shutdown_timeout: float | None = None,
        ssl_shared_lock: bool | None = None,
        max_recv_size: int | None = None,
        backend: str | AbstractAsyncBackend | None = None,
        backend_kwargs: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
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

        self.__socket: AbstractAsyncStreamSocketAdapter | None = None
        self.__backend: AbstractAsyncBackend = backend
        self.__info: _ClientInfo | None = None

        if ssl:
            if _ssl_module is None:
                raise RuntimeError("stdlib ssl module not available")
            if isinstance(ssl, bool):
                ssl = cast("_SSLContext", _ssl_module.create_default_context())
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

        self.__socket_connector: SingleTaskRunner[AbstractAsyncStreamSocketAdapter] | None = None
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

    async def wait_connected(self) -> None:
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
    def __build_info_dict(socket: AbstractAsyncStreamSocketAdapter) -> _ClientInfo:
        socket_proxy = SocketProxy(socket.socket())
        local_address: SocketAddress = new_socket_address(socket.get_local_address(), socket_proxy.family)
        remote_address: SocketAddress = new_socket_address(socket.get_remote_address(), socket_proxy.family)
        return {
            "proxy": socket_proxy,
            "local_address": local_address,
            "remote_address": remote_address,
        }

    def is_connected(self) -> bool:
        return self.__socket is not None and self.__info is not None

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
            except (ConnectionError, TimeoutError):
                # It is normal if there was connection errors during operations. But do not propagate this exception,
                # as we will never reuse this socket
                pass

    async def send_packet(self, packet: _SentPacketT) -> None:
        async with self.__send_lock:
            socket = await self.__ensure_connected(check_socket_is_closing=True)
            if self.__eof_sent:
                raise RuntimeError("send_eof() has been called earlier")
            with self.__convert_socket_error():
                await socket.sendall_fromiter(filter(None, self.__producer(packet)))
                _check_real_socket_state(self.socket)

    async def send_eof(self) -> None:
        try:
            socket = await self.__ensure_connected(check_socket_is_closing=False)
        except ConnectionError:
            return
        if not isinstance(socket, AbstractAsyncHalfCloseableStreamSocketAdapter):
            raise NotImplementedError

        async with self.__send_lock:
            if self.__eof_sent:
                return
            self.__eof_sent = True
            if not socket.is_closing():
                await socket.send_eof()

    async def recv_packet(self) -> _ReceivedPacketT:
        async with self.__receive_lock:
            consumer = self.__consumer
            try:
                return next(consumer)  # If there is enough data from last call to create a packet, return immediately
            except StopIteration:
                pass

            socket = await self.__ensure_connected(check_socket_is_closing=True)
            if self.__eof_reached:
                self.__abort(None)

            bufsize: int = self.__max_recv_size
            backend = self.__backend

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
                # Attempt failed, wait for one iteration
                await backend.coro_yield()

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
        if socket is None:
            return -1
        return socket.socket().fileno()

    def get_backend(self) -> AbstractAsyncBackend:
        return self.__backend

    async def __ensure_connected(self, *, check_socket_is_closing: bool) -> AbstractAsyncStreamSocketAdapter:
        await self.wait_connected()
        assert self.__socket is not None  # nosec assert_used
        socket = self.__socket
        if check_socket_is_closing and socket.is_closing():
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
        if self.__info is None:
            raise _error_from_errno(_errno.ENOTSOCK)
        return self.__info["proxy"]

    @property
    @final
    def max_recv_size(self) -> int:
        return self.__max_recv_size
