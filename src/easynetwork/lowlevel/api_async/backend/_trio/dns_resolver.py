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
"""trio engine for easynetwork.api_async"""

from __future__ import annotations

__all__ = ["TrioDNSResolver"]

import socket as _socket

from .._common.dns_resolver import BaseAsyncDNSResolver
from . import _trio_utils


class TrioDNSResolver(BaseAsyncDNSResolver):
    __slots__ = ()

    async def connect_socket(self, socket: _socket.socket, address: tuple[str, int] | tuple[str, int, int, int]) -> None:
        await _trio_utils.connect_sock_to_resolved_address(socket, address)
