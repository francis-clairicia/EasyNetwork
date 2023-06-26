# -*- coding: utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Network socket module"""

from __future__ import annotations

__all__ = [
    "ACCEPT_CAPACITY_ERRNOS",
    "ACCEPT_CAPACITY_ERROR_SLEEP_TIME",
    "AF_INET",
    "AF_INET6",
    "AddressFamily",
    "ISocket",
    "MAX_DATAGRAM_BUFSIZE",
    "MAX_STREAM_BUFSIZE",
    "SSL_HANDSHAKE_TIMEOUT",
    "SSL_SHUTDOWN_TIMEOUT",
    "SocketProxy",
    "SupportsSocketOptions",
    "new_socket_address",
]

import contextlib
import errno as _errno
import functools
import socket as _socket
from enum import IntEnum, unique
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Final,
    Literal,
    NamedTuple,
    ParamSpec,
    Protocol,
    TypeAlias,
    TypeVar,
    final,
    overload,
)

if TYPE_CHECKING:
    import threading as _threading

    from _typeshed import ReadableBuffer

_P = ParamSpec("_P")
_R = TypeVar("_R")


@unique
class AddressFamily(IntEnum):
    AF_INET = _socket.AF_INET
    AF_INET6 = _socket.AF_INET6

    def __repr__(self) -> str:
        return f"{type(self).__name__}.{self.name}"

    __str__ = __repr__


AF_INET: Final[Literal[AddressFamily.AF_INET]] = AddressFamily.AF_INET
AF_INET6: Final[Literal[AddressFamily.AF_INET6]] = AddressFamily.AF_INET6


class IPv4SocketAddress(NamedTuple):
    host: str
    port: int

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.host}:{self.port}"

    def for_connection(self) -> tuple[str, int]:
        return self.host, self.port


class IPv6SocketAddress(NamedTuple):
    host: str
    port: int
    flowinfo: int = 0
    scope_id: int = 0

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.host}:{self.port}"

    def for_connection(self) -> tuple[str, int]:
        return self.host, self.port


SocketAddress: TypeAlias = IPv4SocketAddress | IPv6SocketAddress


@overload
def new_socket_address(addr: tuple[str, int], family: Literal[AddressFamily.AF_INET]) -> IPv4SocketAddress:
    ...


@overload
def new_socket_address(
    addr: tuple[str, int] | tuple[str, int, int, int], family: Literal[AddressFamily.AF_INET6]
) -> IPv6SocketAddress:
    ...


@overload
def new_socket_address(addr: tuple[Any, ...], family: int) -> SocketAddress:
    ...


def new_socket_address(addr: tuple[Any, ...], family: int) -> SocketAddress:
    match AddressFamily(family):
        case AddressFamily.AF_INET:
            return IPv4SocketAddress(*addr)
        case AddressFamily.AF_INET6:
            return IPv6SocketAddress(*addr)
        case _:  # pragma: no cover
            raise AssertionError


MAX_STREAM_BUFSIZE: Final[int] = 256 * 1024  # 256KiB
MAX_DATAGRAM_BUFSIZE: Final[int] = 64 * 1024  # 64KiB

# Errors that socket operations can return if the socket is closed
CLOSED_SOCKET_ERRNOS = frozenset(
    {
        # Unix
        _errno.EBADF,
        # Windows
        _errno.ENOTSOCK,
    }
)

# Errors that accept(2) can return, and which indicate that the system is
# overloaded
ACCEPT_CAPACITY_ERRNOS = frozenset(
    {
        _errno.EMFILE,
        _errno.ENFILE,
        _errno.ENOMEM,
        _errno.ENOBUFS,
    }
)

# How long to sleep when we get one of those errors
ACCEPT_CAPACITY_ERROR_SLEEP_TIME = 0.100

# Number of seconds to wait for SSL handshake to complete
# The default timeout matches that of Nginx.
SSL_HANDSHAKE_TIMEOUT = 60.0

# Number of seconds to wait for SSL shutdown to complete
# The default timeout mimics lingering_time
SSL_SHUTDOWN_TIMEOUT = 30.0


class SupportsSocketOptions(Protocol):
    @overload
    def getsockopt(self, __level: int, __optname: int, /) -> int:
        ...

    @overload
    def getsockopt(self, __level: int, __optname: int, __buflen: int, /) -> bytes:
        ...

    @overload
    def setsockopt(self, __level: int, __optname: int, __value: int | ReadableBuffer, /) -> None:
        ...

    @overload
    def setsockopt(self, __level: int, __optname: int, __value: None, __optlen: int, /) -> None:
        ...


class ISocket(SupportsSocketOptions, Protocol):
    def fileno(self) -> int:  # pragma: no cover
        ...

    def get_inheritable(self) -> bool:  # pragma: no cover
        ...

    def getpeername(self) -> _socket._RetAddress:  # pragma: no cover
        ...

    def getsockname(self) -> _socket._RetAddress:  # pragma: no cover
        ...

    @property  # pragma: no cover
    def family(self) -> int:
        ...

    @property  # pragma: no cover
    def type(self) -> int:
        ...

    @property  # pragma: no cover
    def proto(self) -> int:
        ...


@final
class SocketProxy:
    __slots__ = ("__socket", "__lock_ctx", "__runner", "__weakref__")

    def __init_subclass__(cls) -> None:  # pragma: no cover
        raise TypeError("SocketProxy cannot be subclassed")

    def __init__(
        self,
        socket: ISocket,
        *,
        lock: Callable[[], _threading.Lock | _threading.RLock] | None = None,
        runner: Callable[[Callable[[], Any]], Any] | None = None,
    ) -> None:
        self.__socket: ISocket = socket
        self.__lock_ctx: Callable[[], _threading.Lock | _threading.RLock] | None = lock
        self.__runner: Callable[[Callable[[], Any]], Any] | None = runner

    def __repr__(self) -> str:
        fd: int = self.fileno()
        s = f"<{type(self).__name__} fd={fd}, " f"family={self.family!s}, type={self.type!s}, " f"proto={self.proto}"

        if fd != -1:
            try:
                laddr = self.getsockname()
                if laddr:
                    s = f"{s}, laddr={laddr}"
            except _socket.error:
                pass
            try:
                raddr = self.getpeername()
                if raddr:
                    s = f"{s}, raddr={raddr}"
            except _socket.error:
                pass

        return f"{s}>"

    def __getstate__(self) -> Any:  # pragma: no cover
        raise TypeError(f"cannot pickle {self.__class__.__name__!r} object")

    def __execute(self, __func: Callable[_P, _R], /, *args: _P.args, **kwargs: _P.kwargs) -> _R:
        with lock_ctx() if (lock_ctx := self.__lock_ctx) is not None else contextlib.nullcontext():
            if (run := self.__runner) is not None:
                if args or kwargs:
                    __func = functools.partial(__func, *args, **kwargs)
                return run(__func)
            return __func(*args, **kwargs)

    def fileno(self) -> int:
        return self.__execute(self.__socket.fileno)

    def dup(self) -> _socket.socket:
        new_socket = _socket.fromfd(self.fileno(), self.family, self.type, self.proto)
        new_socket.setblocking(False)
        return new_socket

    def get_inheritable(self) -> bool:
        return self.__execute(self.__socket.get_inheritable)

    @overload
    def getsockopt(self, __level: int, __optname: int, /) -> int:
        ...

    @overload
    def getsockopt(self, __level: int, __optname: int, __buflen: int, /) -> bytes:
        ...

    def getsockopt(self, *args: Any) -> int | bytes:
        return self.__execute(self.__socket.getsockopt, *args)

    @overload
    def setsockopt(self, __level: int, __optname: int, __value: int | ReadableBuffer, /) -> None:
        ...

    @overload
    def setsockopt(self, __level: int, __optname: int, __value: None, __optlen: int, /) -> None:
        ...

    def setsockopt(self, *args: Any) -> None:
        return self.__execute(self.__socket.setsockopt, *args)

    def getpeername(self) -> SocketAddress:
        socket = self.__socket
        return new_socket_address(self.__execute(socket.getpeername), socket.family)

    def getsockname(self) -> SocketAddress:
        socket = self.__socket
        return new_socket_address(self.__execute(socket.getsockname), socket.family)

    @property
    def family(self) -> AddressFamily:
        return AddressFamily(self.__socket.family)

    @property
    def type(self) -> _socket.SocketKind:
        return _socket.SocketKind(self.__socket.type)

    @property
    def proto(self) -> int:
        return self.__socket.proto
