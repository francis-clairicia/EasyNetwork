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
"""trio engine for easynetwork.api_async
"""

from __future__ import annotations

__all__ = ["TrioDNSResolver"]

import socket as _socket

import trio.socket

from .._common.dns_resolver import BaseAsyncDNSResolver


class TrioDNSResolver(BaseAsyncDNSResolver):
    __slots__ = ()

    async def connect_socket(self, socket: _socket.socket, address: tuple[str, int] | tuple[str, int, int, int]) -> None:
        # TL;DR: Why not directly use trio.socket.socket() function?
        # When giving a fileno, it tries to guess the real family, type and proto of the file descriptor
        # by calling getsockopt(). This extra operation is useless here.
        async_socket = trio.socket.from_stdlib_socket(
            _socket.socket(socket.family, socket.type, socket.proto, fileno=socket.fileno())
        )
        try:
            await async_socket.connect(address)
        except BaseException:
            # If connect() raises an exception, let trio close the socket.
            # NOTE: connect() already closes the socket if trio.Cancelled is raised.
            socket.detach()
            raise
        else:
            # The operation has succeeded, remove the ownership to the temporary socket.
            async_socket.detach()
        finally:
            async_socket.close()
