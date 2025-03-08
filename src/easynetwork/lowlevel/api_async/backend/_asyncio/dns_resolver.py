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
"""asyncio engine for easynetwork.api_async"""

from __future__ import annotations

__all__ = ["AsyncIODNSResolver"]

import asyncio
import socket as _socket
from typing import final

from .._common.dns_resolver import BaseAsyncDNSResolver


@final
class AsyncIODNSResolver(BaseAsyncDNSResolver):
    __slots__ = ()

    async def connect_socket(self, socket: _socket.socket, address: tuple[str, int] | tuple[str, int, int, int]) -> None:
        loop = asyncio.get_running_loop()

        await loop.sock_connect(socket, address)
