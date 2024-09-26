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

import trio

from .... import _utils
from .._common.dns_resolver import BaseAsyncDNSResolver


class TrioDNSResolver(BaseAsyncDNSResolver):
    __slots__ = ()

    async def connect_socket(self, socket: _socket.socket, address: tuple[str, int] | tuple[str, int, int, int]) -> None:
        await trio.lowlevel.checkpoint_if_cancelled()
        try:
            socket.connect(address)
        except BlockingIOError:
            pass
        else:
            await trio.lowlevel.cancel_shielded_checkpoint()
            return

        await trio.lowlevel.wait_writable(socket)
        _utils.check_real_socket_state(socket, error_msg=f"Could not connect to {address!r}: {{strerror}}")
