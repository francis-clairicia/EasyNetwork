# -*- coding: Utf-8 -*-

from __future__ import annotations

__all__ = [
    "check_real_socket_state",
    "restore_timeout_at_end",
]

import contextlib
import os
import socket as _socket
from typing import Iterator


def check_real_socket_state(socket: _socket.socket) -> None:
    """Verify socket saved error and raise OSError if there is one

    On Unix: There is some functions such as socket.send() which do not immediately fail and save the errno
    in SO_ERROR socket option because the error spawn after the action was sent to the kernel (Something weird)

    On Windows: (TODO) There is a similar system but actually this function does not handle it.
    """
    errno = socket.getsockopt(_socket.SOL_SOCKET, _socket.SO_ERROR)
    if errno > 0:
        # The SO_ERROR is automatically reset to zero after getting the value
        raise OSError(errno, os.strerror(errno))


@contextlib.contextmanager
def restore_timeout_at_end(socket: _socket.socket) -> Iterator[float | None]:
    old_timeout: float | None = socket.gettimeout()
    try:
        yield old_timeout
    finally:
        socket.settimeout(old_timeout)
