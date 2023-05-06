# -*- coding: Utf-8 -*-

from __future__ import annotations

__all__ = [
    "check_real_socket_state",
    "error_from_errno",
    "open_listener_sockets_from_getaddrinfo_result",
    "restore_timeout_at_end",
    "set_reuseport",
]

import contextlib
import errno as _errno
import os
import socket as _socket
from typing import TYPE_CHECKING, Any, Iterable, Iterator

if TYPE_CHECKING:
    from .socket import SocketProxy as _SocketProxy


def error_from_errno(errno: int) -> OSError:
    return OSError(errno, os.strerror(errno))


def check_socket_family(family: int) -> None:
    from .socket import AddressFamily

    supported_families: dict[str, int] = dict(AddressFamily.__members__)

    if family not in list(supported_families.values()):
        raise ValueError(f"Only these families are supported: {', '.join(supported_families)}")


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


def ensure_datagram_socket_bound(sock: _socket.socket) -> None:
    assert sock.family in (_socket.AF_INET, _socket.AF_INET6), "Invalid socket family."
    if sock.type != _socket.SOCK_DGRAM:
        raise ValueError("Invalid socket type. Expected SOCK_DGRAM socket.")
    try:
        is_bound: bool = sock.getsockname()[1] > 0
    except OSError as exc:
        if exc.errno != _errno.EINVAL:
            raise
        is_bound = False

    if not is_bound:
        sock.bind(("", 0))


def set_reuseport(sock: _socket.socket) -> None:
    if not hasattr(_socket, "SO_REUSEPORT"):
        raise ValueError("reuse_port not supported by socket module")
    else:
        try:
            sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEPORT, True)
        except OSError:
            raise ValueError("reuse_port not supported by socket module, SO_REUSEPORT defined but not implemented.") from None


def set_tcp_nodelay(sock: _socket.socket | _SocketProxy) -> None:
    try:
        sock.setsockopt(_socket.IPPROTO_TCP, _socket.TCP_NODELAY, True)
    except (OSError, AttributeError):  # pragma: no cover
        pass


def open_listener_sockets_from_getaddrinfo_result(
    infos: Iterable[tuple[int, int, int, str, tuple[Any, ...]]],
    *,
    backlog: int,
    reuse_address: bool,
    reuse_port: bool,
) -> list[_socket.socket]:
    sockets: list[_socket.socket] = []
    with contextlib.ExitStack() as socket_exit_stack:
        errors: list[OSError] = []
        for res in infos:
            af, socktype, proto, _, sa = res
            assert socktype == _socket.SOCK_STREAM, "Expected a SOCK_STREAM socket type"
            try:
                sock = socket_exit_stack.enter_context(contextlib.closing(_socket.socket(af, socktype, proto)))
            except OSError:
                # Assume it's a bad family/type/protocol combination.
                continue
            sockets.append(sock)
            if reuse_address:
                sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, True)
            if reuse_port:
                set_reuseport(sock)
            # Disable IPv4/IPv6 dual stack support (enabled by
            # default on Linux) which makes a single socket
            # listen on both address families.
            if _socket.has_ipv6 and af == _socket.AF_INET6 and hasattr(_socket, "IPPROTO_IPV6"):
                sock.setsockopt(_socket.IPPROTO_IPV6, _socket.IPV6_V6ONLY, True)
            try:
                sock.bind(sa)
            except OSError as exc:
                errors.append(
                    OSError(
                        exc.errno, "error while attempting to bind on address %r: %s" % (sa, exc.strerror.lower())
                    ).with_traceback(exc.__traceback__)
                )
                continue
            sock.listen(backlog)

        if errors:
            try:
                raise ExceptionGroup("Error when trying to create TCP listeners", errors)
            finally:
                errors = []

        # There were no errors, therefore do not close the sockets
        socket_exit_stack.pop_all()

    return sockets
