# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Network socket module"""

from __future__ import annotations

__all__ = [
    "AF_INET",
    "AF_INET6",
    "AddressFamily",
    "SocketProxy",
    "new_socket_address",
]

import socket as _socket
from enum import IntEnum, unique
from typing import Any, Final, Literal, NamedTuple, NoReturn, TypeAlias, overload


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


class SocketProxy:
    __slots__ = ("__socket", "__weakref__")

    def __init__(self, socket: _socket.socket) -> None:
        self.__socket: _socket.socket = socket

    def __repr__(self) -> str:
        s = f"<{type(self).__name__} fd={self.fileno()}, " f"family={self.family!s}, type={self.type!s}, " f"proto={self.proto}"

        if self.fileno() != -1:
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

    def __getstate__(self) -> NoReturn:  # pragma: no cover
        raise TypeError(f"Cannot serialize {type(self).__module__}.{type(self).__qualname__} object")

    def fileno(self) -> int:
        return self.__socket.fileno()

    def dup(self) -> _socket.socket:
        return self.__socket.dup()

    def get_inheritable(self) -> bool:
        return self.__socket.get_inheritable()

    @overload
    def getsockopt(self, __level: int, __optname: int, /) -> int:
        ...

    @overload
    def getsockopt(self, __level: int, __optname: int, __buflen: int, /) -> bytes:
        ...

    def getsockopt(self, *args: Any) -> int | bytes:
        return self.__socket.getsockopt(*args)

    @overload
    def setsockopt(self, __level: int, __optname: int, __value: int | bytes, /) -> None:
        ...

    @overload
    def setsockopt(self, __level: int, __optname: int, __value: None, __optlen: int, /) -> None:
        ...

    def setsockopt(self, *args: Any) -> None:
        self.__socket.setsockopt(*args)

    def getpeername(self) -> SocketAddress:
        socket = self.__socket
        return new_socket_address(socket.getpeername(), socket.family)

    def getsockname(self) -> SocketAddress:
        socket = self.__socket
        return new_socket_address(socket.getsockname(), socket.family)

    @property
    def family(self) -> AddressFamily:
        return AddressFamily(self.__socket.family)

    @property
    def type(self) -> _socket.SocketKind:
        return self.__socket.type

    @property
    def proto(self) -> int:
        return self.__socket.proto
