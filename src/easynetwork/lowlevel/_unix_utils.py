# Copyright 2021-2024, Francis Clairicia-Rose-Claire-Josephine
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
    "LazyPeerCredsContainer",
    "check_unix_socket_family",
    "convert_optional_unix_socket_address",
    "convert_unix_socket_address",
    "is_unix_socket_family",
    "platform_supports_automatic_socket_bind",
]

import os
import socket as _socket
import sys
from collections.abc import Callable
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from .socket import ISocket, UnixCredentials, UnixSocketAddress

_T_Socket = TypeVar("_T_Socket", bound="ISocket")


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
    from .socket import UnixSocketAddress

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


class LazyPeerCredsContainer:
    __slots__ = ("__peer_credentials",)

    def __init__(self) -> None:
        self.__peer_credentials: UnixCredentials | None = None

    def get(self, sock: _T_Socket, get_peer_credentials: Callable[[_T_Socket], UnixCredentials]) -> UnixCredentials:
        if (peer_creds := self.__peer_credentials) is None:
            peer_creds = get_peer_credentials(sock)
            self.__peer_credentials = peer_creds
        return peer_creds
