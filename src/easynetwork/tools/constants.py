# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""EasyNetwork's constants module"""

from __future__ import annotations

__all__ = [
    "ACCEPT_CAPACITY_ERRNOS",
    "ACCEPT_CAPACITY_ERROR_SLEEP_TIME",
    "MAX_DATAGRAM_BUFSIZE",
    "MAX_STREAM_BUFSIZE",
    "SSL_HANDSHAKE_TIMEOUT",
    "SSL_SHUTDOWN_TIMEOUT",
]

import errno as _errno
from typing import Final

MAX_STREAM_BUFSIZE: Final[int] = 256 * 1024  # 256KiB
MAX_DATAGRAM_BUFSIZE: Final[int] = 64 * 1024  # 64KiB

# Errors that socket operations can return if the socket is closed
CLOSED_SOCKET_ERRNOS: Final[frozenset[int]] = frozenset(
    {
        # Unix
        _errno.EBADF,
        # Windows
        _errno.ENOTSOCK,
    }
)

# Errors that accept(2) can return, and which indicate that the system is
# overloaded
ACCEPT_CAPACITY_ERRNOS: Final[frozenset[int]] = frozenset(
    {
        _errno.EMFILE,
        _errno.ENFILE,
        _errno.ENOMEM,
        _errno.ENOBUFS,
    }
)

# How long to sleep when we get one of those errors
ACCEPT_CAPACITY_ERROR_SLEEP_TIME: Final[float] = 0.100

# Number of seconds to wait for SSL handshake to complete
# The default timeout matches that of Nginx.
SSL_HANDSHAKE_TIMEOUT: Final[float] = 60.0

# Number of seconds to wait for SSL shutdown to complete
# The default timeout mimics lingering_time
SSL_SHUTDOWN_TIMEOUT: Final[float] = 30.0