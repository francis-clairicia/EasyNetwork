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
    "ConnectedUDPSocketTransport",
    "SSLSocketTransport",
    "TCPSocketTransport",
]

import selectors
import socket
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, ParamSpec, TypeVar

try:
    import ssl
except ImportError:  # pragma: no cover
    _ssl_module = None
else:
    _ssl_module = ssl
    del ssl

from ....tools._utils import check_socket_no_ssl as _check_socket_no_ssl, is_ssl_socket as _is_ssl_socket
from ....tools.constants import MAX_DATAGRAM_BUFSIZE, SSL_HANDSHAKE_TIMEOUT, SSL_SHUTDOWN_TIMEOUT
from ....tools.socket import SocketProxy
from .base_selector import SelectorDatagramTransport, SelectorStreamTransport, WouldBlockOnRead, WouldBlockOnWrite

if TYPE_CHECKING:
    import ssl as _typing_ssl

_P = ParamSpec("_P")
_R = TypeVar("_R")


def _fill_extra_info(sock: socket.socket, extra: dict[str, Any]) -> None:
    extra["socket"] = SocketProxy(sock)
    extra["sockname"] = sock.getsockname()
    extra["peername"] = sock.getpeername()
    if _is_ssl_socket(sock):
        extra["sslcontext"] = sock.context


def _close_stream_socket(sock: socket.socket) -> None:
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    finally:
        sock.close()


class TCPSocketTransport(SelectorStreamTransport):
    __slots__ = ("__socket", "__extra")

    def __init__(
        self,
        sock: socket.socket,
        retry_interval: float,
        *,
        selector_factory: Callable[[], selectors.BaseSelector] | None = None,
    ) -> None:
        super().__init__(retry_interval=retry_interval, selector_factory=selector_factory)

        _check_socket_no_ssl(sock)
        if sock.type != socket.SOCK_STREAM:
            raise ValueError("A 'SOCK_STREAM' socket is expected")
        self.__socket: socket.socket = sock
        self.__socket.setblocking(False)

        self.__extra: dict[str, Any] = {}
        _fill_extra_info(self.__socket, self.__extra)

    def is_closed(self) -> bool:
        return self.__socket.fileno() < 0

    def close(self) -> None:
        _close_stream_socket(self.__socket)

    def recv_noblock(self, bufsize: int) -> bytes:
        try:
            return self.__socket.recv(bufsize)
        except (BlockingIOError, InterruptedError):
            raise WouldBlockOnRead from None

    def send_noblock(self, data: bytes | bytearray | memoryview) -> int:
        try:
            return self.__socket.send(data)
        except (BlockingIOError, InterruptedError):
            raise WouldBlockOnWrite from None

    def send_eof(self) -> None:
        self.__socket.shutdown(socket.SHUT_WR)

    def fileno(self) -> int:
        return self.__socket.fileno()

    def get_extra_info(self, name: str, default: Any = None) -> Any:
        try:
            return self.__extra[name]
        except KeyError:
            pass
        return super().get_extra_info(name, default)


class SSLSocketTransport(SelectorStreamTransport):
    __slots__ = ("__socket", "__extra", "__ssl_shutdown_timeout")

    def __init__(
        self,
        sock: socket.socket,
        ssl_context: _typing_ssl.SSLContext,
        retry_interval: float,
        *,
        server_side: bool | None = None,
        server_hostname: str | None = None,
        ssl_handshake_timeout: float | None = None,
        ssl_shutdown_timeout: float | None = None,
        standard_compatible: bool = True,
        selector_factory: Callable[[], selectors.BaseSelector] | None = None,
    ) -> None:
        super().__init__(retry_interval=retry_interval, selector_factory=selector_factory)

        _check_socket_no_ssl(sock)
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
        )
        self.__socket.setblocking(False)

        if ssl_handshake_timeout is None:
            ssl_handshake_timeout = SSL_HANDSHAKE_TIMEOUT

        if ssl_shutdown_timeout is None:
            ssl_shutdown_timeout = SSL_SHUTDOWN_TIMEOUT

        self._retry(lambda: self._try_ssl_method(self.__socket.do_handshake, block=False), ssl_handshake_timeout)

        self.__extra: dict[str, Any] = {}
        _fill_extra_info(self.__socket, self.__extra)

        self.__ssl_shutdown_timeout: float = ssl_shutdown_timeout

    def is_closed(self) -> bool:
        return self.__socket.fileno() < 0

    def close(self) -> None:
        try:
            _close_stream_socket(self._retry(lambda: self._try_ssl_method(self.__socket.unwrap), self.__ssl_shutdown_timeout))
        except OSError:
            pass
        finally:
            _close_stream_socket(self.__socket)

    def recv_noblock(self, bufsize: int) -> bytes:
        return self._try_ssl_method(self.__socket.recv, bufsize)

    def send_noblock(self, data: bytes | bytearray | memoryview) -> int:
        return self._try_ssl_method(self.__socket.send, data)

    def send_eof(self) -> None:
        # ssl.SSLSocket.shutdown() would shutdown both read and write streams
        raise NotImplementedError("SSL/TLS API does not support sending EOF.")

    def fileno(self) -> int:
        return self.__socket.fileno()

    def get_extra_info(self, name: str, default: Any = None) -> Any:
        try:
            return self.__extra[name]
        except KeyError:
            pass
        return super().get_extra_info(name, default)

    @staticmethod
    def _try_ssl_method(socket_method: Callable[_P, _R], /, *args: _P.args, **kwargs: _P.kwargs) -> _R:
        assert _ssl_module is not None, "stdlib ssl module not available"  # nosec assert_used
        try:
            return socket_method(*args, **kwargs)
        except (_ssl_module.SSLWantReadError, _ssl_module.SSLSyscallError):
            raise WouldBlockOnRead from None
        except _ssl_module.SSLWantWriteError:
            raise WouldBlockOnWrite from None


class ConnectedUDPSocketTransport(SelectorDatagramTransport):
    __slots__ = ("__socket", "__extra")

    def __init__(
        self,
        sock: socket.socket,
        retry_interval: float,
        *,
        selector_factory: Callable[[], selectors.BaseSelector] | None = None,
    ) -> None:
        super().__init__(retry_interval=retry_interval, selector_factory=selector_factory)

        _check_socket_no_ssl(sock)
        if sock.type != socket.SOCK_DGRAM:
            raise ValueError("A 'SOCK_DGRAM' socket is expected")
        self.__socket: socket.socket = sock
        self.__socket.setblocking(False)

        self.__extra: dict[str, Any] = {}
        _fill_extra_info(self.__socket, self.__extra)

    def is_closed(self) -> bool:
        return self.__socket.fileno() < 0

    def close(self) -> None:
        self.__socket.close()

    def recv_noblock(self) -> bytes:
        try:
            return self.__socket.recv(MAX_DATAGRAM_BUFSIZE)
        except (BlockingIOError, InterruptedError):
            raise WouldBlockOnRead from None

    def send_noblock(self, data: bytes | bytearray | memoryview) -> None:
        try:
            self.__socket.send(data)
        except (BlockingIOError, InterruptedError):
            raise WouldBlockOnWrite from None

    def fileno(self) -> int:
        return self.__socket.fileno()

    def get_extra_info(self, name: str, default: Any = None) -> Any:
        try:
            return self.__extra[name]
        except KeyError:
            pass
        return super().get_extra_info(name, default)