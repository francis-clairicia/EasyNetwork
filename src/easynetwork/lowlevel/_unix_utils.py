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
from __future__ import annotations

__all__ = [
    "UnixCredsContainer",
    "check_unix_socket_family",
    "convert_optional_unix_socket_address",
    "convert_unix_socket_address",
    "is_unix_socket_family",
    "platform_supports_automatic_socket_bind",
]

import functools
import os
import socket as _socket
import sys
from collections.abc import Callable

from .socket import ISocket, UnixCredentials, UnixSocketAddress


def is_unix_socket_family(family: int) -> bool:
    try:
        AF_UNIX: _socket.AddressFamily = _socket.AddressFamily["AF_UNIX"]
    except KeyError:
        return False
    return family == AF_UNIX


def check_unix_socket_family(family: int) -> None:
    if not is_unix_socket_family(family):
        raise ValueError("Only these families are supported: AF_UNIX")


def convert_unix_socket_address(path: str | os.PathLike[str] | bytes | UnixSocketAddress) -> str | bytes:
    if isinstance(path, (str, bytes)):
        path = UnixSocketAddress.from_raw(path)
    elif not isinstance(path, UnixSocketAddress):
        path = UnixSocketAddress.from_pathname(path)
    return path.as_raw()


def convert_optional_unix_socket_address(path: str | os.PathLike[str] | bytes | UnixSocketAddress | None) -> str | bytes | None:
    if path is not None:
        path = convert_unix_socket_address(path)
    return path


def platform_supports_automatic_socket_bind() -> bool:
    # Automatic socket bind feature is available on platforms supporting abstract unix sockets.
    # Currently, only linux platform has this feature.
    return sys.platform == "linux"


class UnixCredsContainer:
    __slots__ = ("__peer_credentials", "__sock")

    def __init__(self, sock: ISocket) -> None:
        check_unix_socket_family(sock.family)
        self.__peer_credentials: UnixCredentials | None = None
        self.__sock: ISocket = sock

    def get(self) -> UnixCredentials:
        if (peer_creds := self.__peer_credentials) is None:
            sock = self.__sock
            get_peer_credentials = _get_peer_credentials_impl_from_platform()
            peer_creds = get_peer_credentials(sock)
            self.__peer_credentials = peer_creds
        return peer_creds


@functools.cache
def _get_peer_credentials_impl_from_platform() -> Callable[[ISocket], UnixCredentials]:
    match sys.platform:
        case "darwin":
            return __get_peer_eid_macos_impl()
        case platform if platform.startswith(("linux", "openbsd", "netbsd")):
            return __get_ucred_impl()
        case platform if platform.startswith(("freebsd", "dragonfly")):
            return __get_peer_eid_bsd_generic_impl()
        case platform:
            raise NotImplementedError(f"There is no implementation available for {platform!r}")


def __get_ucred_impl() -> Callable[[ISocket], UnixCredentials]:
    from errno import EBADF, EINVAL
    from struct import Struct

    from ._errno import error_from_errno

    if sys.platform.startswith("netbsd"):
        # The constants are not defined in _socket module (at least on 3.11).
        # https://man.netbsd.org/unix.4
        SOL_LOCAL: int = 0
        LOCAL_PEEREID: int = 3

        level = SOL_LOCAL
        option = LOCAL_PEEREID
    else:
        from socket import SO_PEERCRED, SOL_SOCKET  # type: ignore[attr-defined, unused-ignore]

        level = SOL_SOCKET
        option = SO_PEERCRED

    _UID_GID_MAX: int = 2**32 - 1

    if sys.platform.startswith("openbsd"):
        # Surprise! The fields order differs.
        # https://unix.stackexchange.com/a/496586

        _ucred_struct = Struct("@IIi")

        def _unpack_ucred(buffer: bytes, /) -> tuple[int, int, int]:
            uid, gid, pid = _ucred_struct.unpack(buffer)
            return pid, uid, gid

    else:
        _ucred_struct = Struct("@iII")

        _unpack_ucred = _ucred_struct.unpack

    def get_peer_credentials(sock: ISocket, /) -> UnixCredentials:
        if sock.fileno() < 0:
            raise error_from_errno(EBADF)

        ucred = UnixCredentials._make(_unpack_ucred(sock.getsockopt(level, option, _ucred_struct.size)))
        if ucred.pid == 0 or ucred.uid == _UID_GID_MAX or ucred.gid == _UID_GID_MAX:
            raise error_from_errno(EINVAL)

        return ucred

    return get_peer_credentials


def __get_peer_eid_macos_impl() -> Callable[[ISocket], UnixCredentials]:
    import ctypes
    import ctypes.util
    from errno import EBADF

    from ._errno import error_from_errno

    # The constants are not defined in _socket module (at least on 3.11).
    # c.f. https://stackoverflow.com/a/67971484
    SOL_LOCAL: int = 0
    LOCAL_PEERPID: int = 2

    c_uid_t = ctypes.c_uint
    c_gid_t = ctypes.c_uint

    if (libc_name := ctypes.util.find_library("c")) is None:
        raise NotImplementedError(f"Could not find libc on {sys.platform!r}")

    libc = ctypes.CDLL(libc_name, use_errno=True)
    libc.getpeereid.argtypes = [ctypes.c_int, ctypes.POINTER(c_uid_t), ctypes.POINTER(c_gid_t)]
    libc.getpeereid.restype = ctypes.c_int

    def get_peer_credentials(sock: ISocket, /) -> UnixCredentials:
        fileno = sock.fileno()
        if fileno < 0:
            raise error_from_errno(EBADF)

        uid = c_uid_t(1)
        gid = c_gid_t(1)
        if libc.getpeereid(fileno, ctypes.byref(uid), ctypes.byref(gid)) != 0:
            raise error_from_errno(ctypes.get_errno())

        pid = sock.getsockopt(SOL_LOCAL, LOCAL_PEERPID)
        return UnixCredentials(pid, uid.value, gid.value)

    return get_peer_credentials


def __get_peer_eid_bsd_generic_impl() -> Callable[[ISocket], UnixCredentials]:
    import ctypes
    import ctypes.util
    from errno import EBADF

    from ._errno import error_from_errno

    c_uid_t = ctypes.c_uint
    c_gid_t = ctypes.c_uint

    if (libc_name := ctypes.util.find_library("c")) is None:
        raise NotImplementedError(f"Could not find libc on {sys.platform!r}")

    libc = ctypes.CDLL(libc_name, use_errno=True)
    libc.getpeereid.argtypes = [ctypes.c_int, ctypes.POINTER(c_uid_t), ctypes.POINTER(c_gid_t)]
    libc.getpeereid.restype = ctypes.c_int

    def get_peer_credentials(sock: ISocket, /) -> UnixCredentials:
        fileno = sock.fileno()
        if fileno < 0:
            raise error_from_errno(EBADF)

        uid = c_uid_t(1)
        gid = c_gid_t(1)
        if libc.getpeereid(fileno, ctypes.byref(uid), ctypes.byref(gid)) != 0:
            raise error_from_errno(ctypes.get_errno())

        return UnixCredentials(None, uid.value, gid.value)

    return get_peer_credentials
