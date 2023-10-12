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
"""Low-level transports module"""

from __future__ import annotations

__all__ = [
    "SSLStreamTransport",
    "SocketDatagramTransport",
    "SocketStreamTransport",
]

import selectors
import socket
from collections import ChainMap
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, ParamSpec, TypeVar

try:
    import ssl
except ImportError:  # pragma: no cover
    _ssl_module = None
else:
    _ssl_module = ssl
    del ssl

from ... import _utils, constants, socket as socket_tools
from . import base_selector

if TYPE_CHECKING:
    import ssl as _typing_ssl

_P = ParamSpec("_P")
_R = TypeVar("_R")


def _close_stream_socket(sock: socket.socket) -> None:
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    finally:
        sock.close()


class SocketStreamTransport(base_selector.SelectorStreamTransport):
    __slots__ = ("__socket",)

    def __init__(
        self,
        sock: socket.socket,
        retry_interval: float,
        *,
        selector_factory: Callable[[], selectors.BaseSelector] | None = None,
    ) -> None:
        super().__init__(retry_interval=retry_interval, selector_factory=selector_factory)

        _utils.check_socket_no_ssl(sock)
        if sock.type != socket.SOCK_STREAM:
            raise ValueError("A 'SOCK_STREAM' socket is expected")
        self.__socket: socket.socket = sock
        self.__socket.setblocking(False)

    def is_closed(self) -> bool:
        return self.__socket.fileno() < 0

    def close(self) -> None:
        _close_stream_socket(self.__socket)

    def recv_noblock(self, bufsize: int) -> bytes:
        try:
            return self.__socket.recv(bufsize)
        except (BlockingIOError, InterruptedError):
            raise base_selector.WouldBlockOnRead(self.__socket.fileno()) from None

    def send_noblock(self, data: bytes | bytearray | memoryview) -> int:
        try:
            return self.__socket.send(data)
        except (BlockingIOError, InterruptedError):
            raise base_selector.WouldBlockOnWrite(self.__socket.fileno()) from None

    def send_eof(self) -> None:
        try:
            self.__socket.shutdown(socket.SHUT_WR)
        except OSError as exc:
            if exc.errno in constants.NOT_CONNECTED_SOCKET_ERRNOS:
                # On some platforms (e.g. macOS), shutdown() raises if the socket is already disconnected.
                pass
            else:
                raise

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        socket = self.__socket
        return socket_tools._get_socket_extra(socket)


class SSLStreamTransport(base_selector.SelectorStreamTransport):
    __slots__ = ("__socket", "__ssl_shutdown_timeout", "__standard_compatible")

    def __init__(
        self,
        sock: socket.socket,
        ssl_context: _typing_ssl.SSLContext,
        retry_interval: float,
        *,
        handshake_timeout: float | None = None,
        shutdown_timeout: float | None = None,
        server_side: bool | None = None,
        server_hostname: str | None = None,
        standard_compatible: bool = True,
        session: _typing_ssl.SSLSession | None = None,
        selector_factory: Callable[[], selectors.BaseSelector] | None = None,
    ) -> None:
        super().__init__(retry_interval=retry_interval, selector_factory=selector_factory)

        if handshake_timeout is None:
            handshake_timeout = constants.SSL_HANDSHAKE_TIMEOUT
        if shutdown_timeout is None:
            shutdown_timeout = constants.SSL_SHUTDOWN_TIMEOUT

        handshake_timeout = _utils.validate_timeout_delay(handshake_timeout, positive_check=True)
        shutdown_timeout = _utils.validate_timeout_delay(shutdown_timeout, positive_check=True)
        standard_compatible = bool(standard_compatible)

        _utils.check_socket_no_ssl(sock)
        if sock.type != socket.SOCK_STREAM:
            raise ValueError("A 'SOCK_STREAM' socket is expected")
        if server_side is None:
            server_side = not server_hostname
        self.__socket: _typing_ssl.SSLSocket = ssl_context.wrap_socket(
            sock,
            server_side=server_side,
            server_hostname=server_hostname,
            suppress_ragged_eofs=not standard_compatible,
            do_handshake_on_connect=False,
            session=session,
        )
        self.__socket.setblocking(False)

        try:
            self._retry(lambda: self._try_ssl_method(self.__socket.do_handshake), handshake_timeout)
        except BaseException:
            self.__socket.close()
            raise

        self.__ssl_shutdown_timeout: float = shutdown_timeout
        self.__standard_compatible: bool = standard_compatible

    def is_closed(self) -> bool:
        return self.__socket.fileno() < 0

    def close(self) -> None:
        try:
            if self.__standard_compatible:
                self._retry(lambda: self._try_ssl_method(self.__socket.unwrap), self.__ssl_shutdown_timeout)
        except (OSError, ValueError):
            pass
        finally:
            _close_stream_socket(self.__socket)

    def recv_noblock(self, bufsize: int) -> bytes:
        return self._try_ssl_method(self.__socket.recv, bufsize)

    def send_noblock(self, data: bytes | bytearray | memoryview) -> int:
        return self._try_ssl_method(self.__socket.send, data)

    def send_eof(self) -> None:
        # ssl.SSLSocket.shutdown() would close both read and write streams
        raise NotImplementedError("SSL/TLS API does not support sending EOF.")

    def _try_ssl_method(self, socket_method: Callable[_P, _R], /, *args: _P.args, **kwargs: _P.kwargs) -> _R:
        if _ssl_module is None:
            raise RuntimeError("stdlib ssl module not available")
        try:
            return socket_method(*args, **kwargs)
        except (_ssl_module.SSLWantReadError, _ssl_module.SSLSyscallError):
            raise base_selector.WouldBlockOnRead(self.__socket.fileno()) from None
        except _ssl_module.SSLWantWriteError:
            raise base_selector.WouldBlockOnWrite(self.__socket.fileno()) from None

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        socket = self.__socket
        return ChainMap(
            socket_tools._get_socket_extra(socket),
            socket_tools._get_tls_extra(socket),
            {
                socket_tools.TLSAttribute.standard_compatible: lambda: self.__standard_compatible,
            },
        )


class SocketDatagramTransport(base_selector.SelectorDatagramTransport):
    __slots__ = ("__socket", "__max_datagram_size")

    def __init__(
        self,
        sock: socket.socket,
        retry_interval: float,
        *,
        max_datagram_size: int = constants.MAX_DATAGRAM_BUFSIZE,
        selector_factory: Callable[[], selectors.BaseSelector] | None = None,
    ) -> None:
        super().__init__(retry_interval=retry_interval, selector_factory=selector_factory)

        if max_datagram_size <= 0:
            raise ValueError("max_datagram_size must not be <= 0")

        self.__max_datagram_size: int = max_datagram_size

        _utils.check_socket_no_ssl(sock)
        if sock.type != socket.SOCK_DGRAM:
            raise ValueError("A 'SOCK_DGRAM' socket is expected")
        self.__socket: socket.socket = sock
        self.__socket.setblocking(False)

    def is_closed(self) -> bool:
        return self.__socket.fileno() < 0

    def close(self) -> None:
        self.__socket.close()

    def recv_noblock(self) -> bytes:
        max_datagram_size: int = self.__max_datagram_size
        try:
            return self.__socket.recv(max_datagram_size)
        except (BlockingIOError, InterruptedError):
            raise base_selector.WouldBlockOnRead(self.__socket.fileno()) from None

    def send_noblock(self, data: bytes | bytearray | memoryview) -> None:
        try:
            self.__socket.send(data)
        except (BlockingIOError, InterruptedError):
            raise base_selector.WouldBlockOnWrite(self.__socket.fileno()) from None

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        socket = self.__socket
        return socket_tools._get_socket_extra(socket)
