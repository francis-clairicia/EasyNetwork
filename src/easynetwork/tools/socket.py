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
    "MAX_DATAGRAM_SIZE",
    "SHUT_RD",
    "SHUT_RDWR",
    "SHUT_WR",
    "ShutdownFlag",
    "guess_best_recv_size",
    "new_socket_address",
]

import os
import socket as _socket
from enum import IntEnum, unique
from typing import Any, Final, Literal, NamedTuple, TypeAlias, overload


@unique
class AddressFamily(IntEnum):
    AF_INET = _socket.AF_INET
    AF_INET6 = _socket.AF_INET6

    def __repr__(self) -> str:
        return f"{type(self).__name__}.{self.name}"

    __str__ = __repr__


@unique
class ShutdownFlag(IntEnum):
    SHUT_RD = _socket.SHUT_RD
    SHUT_RDWR = _socket.SHUT_RDWR
    SHUT_WR = _socket.SHUT_WR

    def __repr__(self) -> str:
        return f"{type(self).__name__}.{self.name}"

    __str__ = __repr__


AF_INET: Final[Literal[AddressFamily.AF_INET]] = AddressFamily.AF_INET
AF_INET6: Final[Literal[AddressFamily.AF_INET6]] = AddressFamily.AF_INET6
SHUT_RD: Final[Literal[ShutdownFlag.SHUT_RD]] = ShutdownFlag.SHUT_RD
SHUT_RDWR: Final[Literal[ShutdownFlag.SHUT_RDWR]] = ShutdownFlag.SHUT_RDWR
SHUT_WR: Final[Literal[ShutdownFlag.SHUT_WR]] = ShutdownFlag.SHUT_WR


MAX_DATAGRAM_SIZE: Final[int] = 64 * 1024  # 64 KiB


class IPv4SocketAddress(NamedTuple):
    host: str
    port: int

    def __str__(self) -> str:
        return f"{self.host}:{self.port}"

    def for_connection(self) -> tuple[str, int]:
        return self.host, self.port


class IPv6SocketAddress(NamedTuple):
    host: str
    port: int
    flowinfo: int = 0
    scope_id: int = 0

    def __str__(self) -> str:
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
        case _:
            return IPv4SocketAddress(addr[0], addr[1])


def guess_best_recv_size(socket: _socket.socket) -> int:
    try:
        socket_stat = os.fstat(socket.fileno())
    except OSError:  # Will not work for sockets which have not a real file descriptor (e.g. on Windows)
        pass
    else:
        if (blksize := getattr(socket_stat, "st_blksize", 0)) > 0:
            return blksize

    from io import DEFAULT_BUFFER_SIZE

    return DEFAULT_BUFFER_SIZE
