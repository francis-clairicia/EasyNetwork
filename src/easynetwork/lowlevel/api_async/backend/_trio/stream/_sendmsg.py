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

__all__ = ["supports_async_socket_sendmsg"]

from abc import abstractmethod
from collections.abc import Awaitable, Iterable
from typing import TYPE_CHECKING, Protocol, TypeGuard

import trio

if TYPE_CHECKING:
    from _typeshed import ReadableBuffer


class _SupportsAsyncSocketSendMSG(Protocol):
    @abstractmethod
    def sendmsg(self, buffers: Iterable[ReadableBuffer], /) -> Awaitable[int]: ...


def supports_async_socket_sendmsg(sock: trio.socket.SocketType) -> TypeGuard[_SupportsAsyncSocketSendMSG]:
    return hasattr(sock, "sendmsg")
