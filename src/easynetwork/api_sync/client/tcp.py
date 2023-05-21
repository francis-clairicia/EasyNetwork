# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Network client module"""

from __future__ import annotations

__all__ = ["TCPNetworkClient"]

import contextlib as _contextlib
import errno as _errno
import socket as _socket
from threading import Lock as _Lock
from time import monotonic as _time_monotonic
from typing import TYPE_CHECKING, Any, Callable, Generic, Iterator, TypeVar, final, overload

from ...exceptions import ClientClosedError, StreamProtocolParseError
from ...protocol import StreamProtocol
from ...tools._utils import (
    check_real_socket_state as _check_real_socket_state,
    check_socket_family as _check_socket_family,
    check_socket_no_ssl as _check_socket_no_ssl,
    concatenate_chunks as _concatenate_chunks,
    error_from_errno as _error_from_errno,
    is_ssl_eof_error as _is_ssl_eof_error,
    is_ssl_socket as _is_ssl_socket,
    replace_kwargs as _replace_kwargs,
    retry_socket_method as _retry_socket_method,
    retry_ssl_socket_method as _retry_ssl_socket_method,
    set_tcp_nodelay as _set_tcp_nodelay,
    ssl_do_not_ignore_unexpected_eof as _ssl_do_not_ignore_unexpected_eof,
)
from ...tools.socket import MAX_STREAM_BUFSIZE, SocketAddress, SocketProxy, new_socket_address
from ...tools.stream import StreamDataConsumer
from .abc import AbstractNetworkClient

if TYPE_CHECKING:
    from ssl import SSLContext as _SSLContext

_ReceivedPacketT = TypeVar("_ReceivedPacketT")
_SentPacketT = TypeVar("_SentPacketT")


class TCPNetworkClient(AbstractNetworkClient[_SentPacketT, _ReceivedPacketT], Generic[_SentPacketT, _ReceivedPacketT]):
    __slots__ = (
        "__socket",
        "__socket_proxy",
        "__send_lock",
        "__receive_lock",
        "__socket_lock",
        "__producer",
        "__consumer",
        "__addr",
        "__peer",
        "__eof_reached",
        "__max_recv_size",
        "__ssl_shutdown_timeout",
    )

    @overload
    def __init__(
        self,
        address: tuple[str, int],
        /,
        protocol: StreamProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        connect_timeout: float | None = ...,
        local_address: tuple[str, int] | None = ...,
        ssl: _SSLContext | bool | None = ...,
        server_hostname: str | None = ...,
        ssl_handshake_timeout: float | None = ...,
        ssl_shutdown_timeout: float | None = ...,
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
        ssl: _SSLContext | bool | None = ...,
        server_hostname: str | None = ...,
        ssl_handshake_timeout: float | None = ...,
        ssl_shutdown_timeout: float | None = ...,
        max_recv_size: int | None = ...,
    ) -> None:
        ...

    def __init__(
        self,
        __arg: _socket.socket | tuple[str, int],
        /,
        protocol: StreamProtocol[_SentPacketT, _ReceivedPacketT],
        *,
        ssl: _SSLContext | bool | None = None,
        server_hostname: str | None = None,
        ssl_handshake_timeout: float | None = None,
        ssl_shutdown_timeout: float | None = None,
        max_recv_size: int | None = None,
        **kwargs: Any,
    ) -> None:
        self.__socket: _socket.socket | None = None  # If any exception occurs, the client will already be in a closed state
        super().__init__()
        self.__send_lock = _Lock()
        self.__receive_lock = _Lock()
        self.__socket_lock = _Lock()

        if server_hostname is not None and not ssl:
            raise ValueError("server_hostname is only meaningful with ssl")

        if ssl_handshake_timeout is not None and not ssl:
            raise ValueError("ssl_handshake_timeout is only meaningful with ssl")

        if ssl_shutdown_timeout is not None and not ssl:
            raise ValueError("ssl_shutdown_timeout is only meaningful with ssl")

        socket: _socket.socket
        match __arg:
            case _socket.socket() as socket if not kwargs:
                if server_hostname is None and ssl:
                    raise ValueError("You must set server_hostname when using ssl without a host")
                pass
            case (str(host), int(port)):
                if server_hostname is None and ssl:
                    # Use host as default for server_hostname.  It is an error
                    # if host is empty or not set, e.g. when an
                    # already-connected socket was passed or when only a port
                    # is given.  To avoid this error, you can pass
                    # server_hostname='' -- this will bypass the hostname
                    # check.  (This also means that if host is a numeric
                    # IP/IPv6 address, we will attempt to verify that exact
                    # address; this will probably fail, but it is possible to
                    # create a certificate for a specific IP address, so we
                    # don't judge it here.)
                    if not host:
                        raise ValueError("You must set server_hostname when using ssl without a host")
                    server_hostname = host
                _replace_kwargs(kwargs, {"local_address": "source_address", "connect_timeout": "timeout"})
                kwargs.setdefault("timeout", None)
                socket = _socket.create_connection((host, port), **kwargs, all_errors=True)
            case _:  # pragma: no cover
                raise TypeError("Invalid arguments")

        try:
            if socket.type != _socket.SOCK_STREAM:
                raise ValueError("Invalid socket type")

            _check_socket_family(socket.family)
            _check_socket_no_ssl(socket)

            if max_recv_size is None:
                max_recv_size = MAX_STREAM_BUFSIZE
            if not isinstance(max_recv_size, int) or max_recv_size <= 0:
                raise ValueError("'max_recv_size' must be a strictly positive integer")

            # Do not use global default timeout here
            socket.settimeout(0)

            if ssl:
                if isinstance(ssl, bool):
                    from ssl import create_default_context

                    ssl = create_default_context()
                    if not server_hostname:
                        ssl.check_hostname = False
                    _ssl_do_not_ignore_unexpected_eof(ssl)
                if not server_hostname:
                    server_hostname = None
                socket = ssl.wrap_socket(
                    socket,
                    server_side=False,
                    do_handshake_on_connect=False,
                    suppress_ragged_eofs=False,  # Suppressed or not, it will be transformed to a ConnectionAbortedError so...
                    server_hostname=server_hostname,
                )
                if ssl_handshake_timeout is None:
                    from ...tools.socket import SSL_HANDSHAKE_TIMEOUT

                    ssl_handshake_timeout = SSL_HANDSHAKE_TIMEOUT

                _retry_ssl_socket_method(socket, ssl_handshake_timeout, socket.do_handshake, block=False)

                if ssl_shutdown_timeout is None:
                    from ...tools.socket import SSL_SHUTDOWN_TIMEOUT

                    ssl_shutdown_timeout = SSL_SHUTDOWN_TIMEOUT

            _set_tcp_nodelay(socket)

            self.__addr: SocketAddress = new_socket_address(socket.getsockname(), socket.family)
            self.__peer: SocketAddress = new_socket_address(socket.getpeername(), socket.family)
            self.__producer: Callable[[_SentPacketT], Iterator[bytes]] = protocol.generate_chunks
            self.__consumer: StreamDataConsumer[_ReceivedPacketT] = StreamDataConsumer(protocol)
            self.__socket_proxy = SocketProxy(socket, lock=self.__socket_lock)
            self.__eof_reached: bool = False
            self.__max_recv_size: int = max_recv_size
            self.__ssl_shutdown_timeout: float | None = ssl_shutdown_timeout
        except BaseException:
            socket.close()
            raise

        self.__socket = socket  # There was no errors

    def __del__(self) -> None:  # pragma: no cover
        try:
            socket: _socket.socket | None = self.__socket
        except AttributeError:
            return
        if socket is not None:
            socket.close()

    def __repr__(self) -> str:
        socket = self.__socket
        if socket is None:
            return f"<{type(self).__name__} closed>"
        return f"<{type(self).__name__} socket={socket!r}>"

    @final
    def is_closed(self) -> bool:
        with self.__socket_lock:
            return self.__socket is None

    def close(self) -> None:
        with self.__send_lock, self.__socket_lock:
            if (socket := self.__socket) is None:
                return
            self.__socket = None
            try:
                if not self.__eof_reached and _is_ssl_socket(socket):
                    with self.__convert_ssl_eof_error():
                        socket = _retry_ssl_socket_method(socket, self.__ssl_shutdown_timeout, socket.unwrap)
            except ConnectionError:
                # It is normal if there was connection errors during operations. But do not propagate this exception,
                # as we will never reuse this socket
                pass
            finally:
                socket.close()

    def send_packet(self, packet: _SentPacketT) -> None:
        with self.__send_lock:
            socket = self.__ensure_connected()
            data: bytes = _concatenate_chunks(self.__producer(packet))
            buffer = memoryview(data)
            try:
                remaning: int = len(data)
                while remaning > 0:
                    nb_bytes_sent: int
                    if _is_ssl_socket(socket):
                        with self.__convert_ssl_eof_error():
                            nb_bytes_sent = _retry_ssl_socket_method(socket, None, socket.send, buffer.toreadonly())
                    else:
                        nb_bytes_sent = _retry_socket_method(socket, None, "write", socket.send, buffer.toreadonly())
                    assert nb_bytes_sent >= 0, "socket.send() returned a negative integer"
                    _check_real_socket_state(socket)
                    remaning -= nb_bytes_sent
                    buffer = buffer[nb_bytes_sent:]
            finally:
                del buffer, data

    def recv_packet(self, timeout: float | None = None) -> _ReceivedPacketT:
        with self.__receive_lock:
            consumer = self.__consumer
            next_packet = self.__next_packet
            try:
                return next_packet(consumer)  # If there is enough data from last call to create a packet, return immediately
            except StopIteration:
                pass
            socket = self.__ensure_connected()
            bufsize: int = self.__max_recv_size
            monotonic = _time_monotonic  # pull function to local namespace

            while True:
                try:
                    _start = monotonic()
                    chunk: bytes
                    if _is_ssl_socket(socket):
                        with self.__convert_ssl_eof_error():
                            chunk = _retry_ssl_socket_method(socket, timeout, socket.recv, bufsize)
                    else:
                        chunk = _retry_socket_method(socket, timeout, "read", socket.recv, bufsize)
                    _end = monotonic()
                except TimeoutError as exc:
                    if timeout is None:  # pragma: no cover
                        raise RuntimeError("socket.recv() timed out with timeout=None ?") from exc
                    break
                if not chunk:
                    self.__eof_reached = True
                    raise _error_from_errno(_errno.ECONNABORTED)
                consumer.feed(chunk)
                try:
                    return next_packet(consumer)
                except StopIteration:
                    if timeout is not None:
                        if timeout > 0:
                            timeout -= _end - _start
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

    def __ensure_connected(self) -> _socket.socket:
        if (socket := self.__socket) is None:
            raise ClientClosedError("Closed client")
        if self.__eof_reached:
            raise _error_from_errno(_errno.ECONNABORTED)
        return socket

    @_contextlib.contextmanager
    def __convert_ssl_eof_error(self) -> Iterator[None]:
        import ssl

        try:
            yield
        except ssl.SSLError as exc:
            if isinstance(exc, ssl.SSLZeroReturnError) or _is_ssl_eof_error(exc):
                self.__eof_reached = True
                raise _error_from_errno(_errno.ECONNABORTED) from exc
            raise

    def get_local_address(self) -> SocketAddress:
        return self.__addr

    def get_remote_address(self) -> SocketAddress:
        return self.__peer

    def fileno(self) -> int:
        with self.__socket_lock:
            if (socket := self.__socket) is None:
                return -1
            return socket.fileno()

    @property
    @final
    def socket(self) -> SocketProxy:
        return self.__socket_proxy

    @property
    @final
    def max_recv_size(self) -> int:
        return self.__max_recv_size
