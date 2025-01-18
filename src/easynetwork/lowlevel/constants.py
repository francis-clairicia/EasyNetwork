# Copyright 2021-2025, Francis Clairicia-Rose-Claire-Josephine
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
#
"""EasyNetwork's constants module."""

from __future__ import annotations

__all__ = [
    "ACCEPT_CAPACITY_ERRNOS",
    "ACCEPT_CAPACITY_ERROR_SLEEP_TIME",
    "CLOSED_SOCKET_ERRNOS",
    "DEFAULT_SERIALIZER_LIMIT",
    "DEFAULT_STREAM_BUFSIZE",
    "IGNORABLE_ACCEPT_ERRNOS",
    "MAX_DATAGRAM_BUFSIZE",
    "NOT_CONNECTED_SOCKET_ERRNOS",
    "SC_IOV_MAX",
    "SSL_HANDSHAKE_TIMEOUT",
    "SSL_SHUTDOWN_TIMEOUT",
]

import errno as _errno
from typing import Final

# Buffer size for a recv(2) operation
DEFAULT_STREAM_BUFSIZE: Final[int] = 16 * 1024  # 16KiB

# Buffer size for a recvfrom(2) operation
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

# Errors that socket operations can return if the socket is not connected
NOT_CONNECTED_SOCKET_ERRNOS: Final[frozenset[int]] = frozenset(
    {
        # Most of the operating systems
        _errno.ENOTCONN,
        # macOS
        _errno.EINVAL,
    }
)

# Errors that accept(2) can return, and which indicate that the system is overloaded
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

# Taken from Trio project
# Errors that accept(2) can return, and can be skipped
IGNORABLE_ACCEPT_ERRNOS: Final[frozenset[int]] = frozenset(
    {
        errno
        for name in (
            # Linux can do this when the a connection is denied by the firewall
            "EPERM",
            # BSDs with an early close/reset
            "ECONNABORTED",
            # All the other miscellany noted above -- may not happen in practice, but
            # whatever.
            "EPROTO",
            "ENETDOWN",
            "ENOPROTOOPT",
            "EHOSTDOWN",
            "ENONET",
            "EHOSTUNREACH",
            "EOPNOTSUPP",
            "ENETUNREACH",
            "ENOSR",
            "ESOCKTNOSUPPORT",
            "EPROTONOSUPPORT",
            "ETIMEDOUT",
            "ECONNRESET",
        )
        if (errno := getattr(_errno, name, None)) is not None
    }
)

# Number of seconds to wait for SSL handshake to complete
# The default timeout matches that of Nginx.
SSL_HANDSHAKE_TIMEOUT: Final[float] = 60.0

# Number of seconds to wait for SSL shutdown to complete
# The default timeout mimics lingering_time
SSL_SHUTDOWN_TIMEOUT: Final[float] = 30.0

# "Connection Attempt Delay" for concurrent connections
# Recommended value by the RFC 6555
HAPPY_EYEBALLS_DELAY: Final[float] = 0.25

# Buffer size limit when waiting for a byte sequence
DEFAULT_SERIALIZER_LIMIT: Final[int] = 64 * 1024  # 64 KiB


def __get_sysconf(name: str, /) -> int:
    import os

    try:
        # os.sysconf() can return a negative value if 'name' is not defined
        return os.sysconf(name)  # type: ignore[attr-defined,unused-ignore]
    except (AttributeError, OSError):
        return -1


# Maximum number of buffer that can accept sendmsg(2)
# Can be a negative value
SC_IOV_MAX: Final[int] = __get_sysconf("SC_IOV_MAX")

del __get_sysconf
