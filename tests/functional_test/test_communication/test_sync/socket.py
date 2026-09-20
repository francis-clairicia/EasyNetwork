from __future__ import annotations

import socket
import ssl
from typing import Any, Self, overload


class StreamSocket:
    def __init__(self, sock: socket.socket) -> None:
        self.__sock: socket.socket = sock
        self.__read_buf = sock.makefile("rb")

    @classmethod
    def open_tcp_connection(
        cls,
        host: str,
        port: int,
        *,
        connect_timeout: float | None = None,
        ssl_context: ssl.SSLContext | None = None,
        server_hostname: str | None = None,
        ssl_handshake_timeout: float | None = None,
    ) -> Self:
        if connect_timeout is None:
            connect_timeout = socket.getdefaulttimeout()
        sock = socket.create_connection((host, port), timeout=connect_timeout, all_errors=True)
        try:
            if ssl_context:
                sock.settimeout(ssl_handshake_timeout)
                sock = ssl_context.wrap_socket(sock, server_hostname=server_hostname)
        except BaseException:
            sock.close()
            raise
        return cls(sock)

    def __del__(self) -> None:
        self.__sock.close()
        self.__read_buf.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: Any) -> None:
        del args
        self.close()

    def close(self) -> None:
        if isinstance(self.__sock, ssl.SSLSocket):
            try:
                self.__sock.unwrap()
            except (OSError, ValueError):
                pass
        self.__sock.close()
        self.__read_buf.close()

    def abort(self) -> None:
        self.__sock.close()
        self.__read_buf.close()

    def set_timeout(self, timeout: float | None) -> None:
        self.__sock.settimeout(timeout)

    def recv(self, bufsize: int) -> bytes:
        assert bufsize > 0
        return self.__read_buf.read(bufsize)

    def readline(self) -> bytes:
        return self.__read_buf.readline()

    def send_all(self, data: bytes | bytearray | memoryview) -> None:
        self.__sock.sendall(data)

    def send_eof(self) -> None:
        self.__sock.shutdown(socket.SHUT_WR)

    def getsockname(self) -> socket._RetAddress:
        return self.__sock.getsockname()

    def getpeername(self) -> socket._RetAddress:
        return self.__sock.getpeername()

    @overload
    def getsockopt(self, level: int, optname: int, /) -> int: ...

    @overload
    def getsockopt(self, level: int, optname: int, buflen: int, /) -> bytes: ...

    def getsockopt(self, *args: Any) -> int | bytes:
        return self.__sock.getsockopt(*args)

    @overload
    def setsockopt(self, level: int, optname: int, value: int | bytes, /) -> None: ...

    @overload
    def setsockopt(self, level: int, optname: int, value: None, optlen: int, /) -> None: ...

    def setsockopt(self, *args: Any) -> None:
        self.__sock.setsockopt(*args)
