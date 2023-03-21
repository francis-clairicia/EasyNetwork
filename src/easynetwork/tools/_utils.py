# -*- coding: Utf-8 -*-

from __future__ import annotations

__all__ = [
    "check_real_socket_state",
    "error_from_errno",
    "restore_timeout_at_end",
]

import contextlib
import os
import socket as _socket
from typing import Iterable, Iterator


def error_from_errno(errno: int) -> OSError:
    return OSError(errno, os.strerror(errno))


def check_real_socket_state(socket: _socket.socket) -> None:
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
