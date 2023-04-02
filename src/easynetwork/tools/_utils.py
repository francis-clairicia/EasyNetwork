# -*- coding: Utf-8 -*-

from __future__ import annotations

__all__ = [
    "check_real_socket_state",
    "error_from_errno",
    "ipaddr_info",
    "restore_timeout_at_end",
]

import contextlib
import os
import socket as _socket
from typing import TYPE_CHECKING, Any, Iterable, Iterator

if TYPE_CHECKING:
    from .socket import SocketProxy as _SocketProxy


def error_from_errno(errno: int) -> OSError:
    return OSError(errno, os.strerror(errno))


def check_real_socket_state(socket: _socket.socket | _SocketProxy) -> None:
    """Verify socket saved error and raise OSError if there is one

    There is some functions such as socket.send() which do not immediately fail and save the errno
    in SO_ERROR socket option because the error spawn after the action was sent to the kernel (Something weird)

    On Windows: (TODO) The returned value should be the error returned by WSAGetLastError(), but the socket methods always call
    this function to raise an error, so getsockopt(SO_ERROR) will most likely always return zero :)
    """
    errno = socket.getsockopt(_socket.SOL_SOCKET, _socket.SO_ERROR)
    if errno > 0:
        # The SO_ERROR is automatically reset to zero after getting the value
        raise error_from_errno(errno)


@contextlib.contextmanager
def restore_timeout_at_end(socket: _socket.socket) -> Iterator[float | None]:
    old_timeout: float | None = socket.gettimeout()
    try:
        yield old_timeout
    finally:
        socket.settimeout(old_timeout)


def concatenate_chunks(chunks_iterable: Iterable[bytes]) -> bytes:
    # The list call should be roughly
    # equivalent to the PySequence_Fast that ''.join() would do.
    return b"".join(list(chunks_iterable))


# Taken from asyncio.base_events module
# https://github.com/python/cpython/blob/v3.11.2/Lib/asyncio/base_events.py#L99
def ipaddr_info(
    host: str | bytes | None,
    port: str | bytes | int | None,
    family: int,
    type: int,
    proto: int,
    flowinfo: int = 0,
    scopeid: int = 0,
) -> tuple[int, int, int, str, tuple[Any, ...]] | None:
    # Try to skip getaddrinfo if "host" is already an IP. Users might have
    # handled name resolution in their own code and pass in resolved IPs.
    if not hasattr(_socket, "inet_pton"):
        return None

    if proto not in {0, _socket.IPPROTO_TCP, _socket.IPPROTO_UDP} or host is None:
        return None

    if type == _socket.SOCK_STREAM:
        proto = _socket.IPPROTO_TCP
    elif type == _socket.SOCK_DGRAM:
        proto = _socket.IPPROTO_UDP
    else:
        return None

    if port is None:
        port = 0
    elif isinstance(port, bytes) and port == b"":
        port = 0
    elif isinstance(port, str) and port == "":
        port = 0
    else:
        # If port's a service name like "http", don't skip getaddrinfo.
        try:
            port = int(port)
        except (TypeError, ValueError):
            return None

    afs: list[int]
    if family == _socket.AF_UNSPEC:
        afs = [_socket.AF_INET]
        if _socket.has_ipv6:
            afs.append(_socket.AF_INET6)
    else:
        afs = [family]

    if isinstance(host, bytes):
        host = host.decode("idna")
    if "%" in host:
        # Linux's inet_pton doesn't accept an IPv6 zone index after host,
        # like '::1%lo0'.
        return None

    for af in afs:
        try:
            _socket.inet_pton(af, host)
            # The host has already been resolved.
            if _socket.has_ipv6 and af == _socket.AF_INET6:
                return af, type, proto, "", (host, port, flowinfo, scopeid)
            else:
                return af, type, proto, "", (host, port)
        except OSError:
            pass

    # "host" is not an IP address.
    return None
