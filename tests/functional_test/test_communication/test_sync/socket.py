from __future__ import annotations

import socket
import ssl
import sys
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, Self, overload

if sys.platform != "win32":
    from socket import MSG_CTRUNC, MSG_TRUNC, MsgFlag

    from easynetwork.lowlevel.socket import SocketAncillary

    try:
        from socket import CMSG_SPACE
    except ImportError:
        from socket import CMSG_LEN as CMSG_SPACE

    if TYPE_CHECKING:
        from _socket import _CMSGArg, _RetAddress

    _MAX_ANCDATA_SIZE = 8192

    def _check_recvmsg_return_flags(flags: int) -> None:
        assert (flags & (MSG_TRUNC | MSG_CTRUNC)) == 0, f"messages truncated (flags=={MsgFlag(flags)})"

    def _sock_recvmsg(sock: socket.SocketType, bufsize: int) -> tuple[bytes, SocketAncillary, _RetAddress]:
        data, cmsgs, flags, address = sock.recvmsg(bufsize, CMSG_SPACE(_MAX_ANCDATA_SIZE))
        _check_recvmsg_return_flags(flags)
        ancillary = SocketAncillary()
        ancillary.update_from_raw(cmsgs)
        return data, ancillary, address


class StreamSocket:
    def __init__(self, sock: socket.socket) -> None:
        assert sock.type == socket.SOCK_STREAM
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
        sock.settimeout(socket.getdefaulttimeout())
        return cls(sock)

    if sys.platform != "win32":

        @classmethod
        def open_unix_connection(
            cls,
            path: str | bytes,
            *,
            connect_timeout: float | None = None,
            local_path: str | bytes | None = None,
        ) -> Self:
            if connect_timeout is None:
                connect_timeout = socket.getdefaulttimeout()
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                if local_path is not None:
                    sock.bind(local_path)
                sock.settimeout(connect_timeout)
                sock.connect(path)
            except BaseException:
                sock.close()
                raise
            sock.settimeout(socket.getdefaulttimeout())
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

    if sys.platform != "win32":

        def recvmsg(self, bufsize: int = 1024) -> tuple[bytes, SocketAncillary]:
            data, ancillary, _ = _sock_recvmsg(self.__sock, bufsize)
            return data, ancillary

    def send_all(self, data: bytes | bytearray | memoryview) -> None:
        self.__sock.sendall(data)

    if sys.platform != "win32":

        def sendmsg(self, data: Iterable[bytes | bytearray | memoryview], ancdata: Iterable[_CMSGArg]) -> None:
            data = list(data)
            ancdata = list(ancdata)
            self.__sock.sendmsg(data, ancdata)

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
