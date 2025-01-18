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
"""Internal helper for default implementation of iter_received_packets() for clients."""

from __future__ import annotations

__all__ = ["AsyncClientRecvIterator", "ClientRecvIterator"]

from collections.abc import AsyncIterator, Iterator
from typing import Any

from .._typevars import _T_ReceivedPacket
from ..lowlevel import _utils
from .abc import AbstractAsyncNetworkClient, AbstractNetworkClient


class ClientRecvIterator(Iterator[_T_ReceivedPacket]):
    __slots__ = (
        "__client",
        "__timeout",
    )

    def __init__(self, client: AbstractNetworkClient[Any, _T_ReceivedPacket], timeout: float | None) -> None:
        super().__init__()
        self.__client: AbstractNetworkClient[Any, _T_ReceivedPacket] = client
        self.__timeout: float | None = timeout

    def __next__(self) -> _T_ReceivedPacket:
        try:
            with _utils.ElapsedTime() as elapsed:
                packet = self.__client.recv_packet(timeout=self.__timeout)
        except OSError as exc:
            raise StopIteration from exc
        if self.__timeout is not None:
            self.__timeout = elapsed.recompute_timeout(self.__timeout)
        return packet


class AsyncClientRecvIterator(AsyncIterator[_T_ReceivedPacket]):
    __slots__ = (
        "__client",
        "__backend",
        "__timeout",
    )

    def __init__(self, client: AbstractAsyncNetworkClient[Any, _T_ReceivedPacket], timeout: float | None) -> None:
        super().__init__()
        if timeout is None:
            timeout = float("inf")
        self.__client: AbstractAsyncNetworkClient[Any, _T_ReceivedPacket] = client
        self.__timeout: float = timeout
        self.__backend = client.backend()

    async def __anext__(self) -> _T_ReceivedPacket:
        try:
            with self.__backend.timeout(self.__timeout), _utils.ElapsedTime() as elapsed:
                packet = await self.__client.recv_packet()
        except OSError as exc:
            raise StopAsyncIteration from exc
        self.__timeout = elapsed.recompute_timeout(self.__timeout)
        return packet
