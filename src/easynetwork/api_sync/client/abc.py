# Copyright 2021-2023, Francis Clairicia-Rose-Claire-Josephine
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
"""Network client module"""

from __future__ import annotations

__all__ = ["AbstractNetworkClient"]

import time
from abc import ABCMeta, abstractmethod
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, Generic, Self

from ..._typevars import _ReceivedPacketT, _SentPacketT
from ...tools.socket import SocketAddress

if TYPE_CHECKING:
    from types import TracebackType


class AbstractNetworkClient(Generic[_SentPacketT, _ReceivedPacketT], metaclass=ABCMeta):
    __slots__ = ("__weakref__",)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None) -> None:
        self.close()

    def __getstate__(self) -> Any:  # pragma: no cover
        raise TypeError(f"cannot pickle {self.__class__.__name__!r} object")

    @abstractmethod
    def is_closed(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_local_address(self) -> SocketAddress:
        raise NotImplementedError

    @abstractmethod
    def get_remote_address(self) -> SocketAddress:
        raise NotImplementedError

    @abstractmethod
    def send_packet(self, packet: _SentPacketT, *, timeout: float | None = ...) -> None:
        raise NotImplementedError

    @abstractmethod
    def recv_packet(self, *, timeout: float | None = ...) -> _ReceivedPacketT:
        raise NotImplementedError

    def iter_received_packets(self, *, timeout: float | None = 0) -> Iterator[_ReceivedPacketT]:
        perf_counter = time.perf_counter

        while True:
            try:
                _start = perf_counter()
                packet = self.recv_packet(timeout=timeout)
                _end = perf_counter()
            except OSError:
                return
            yield packet
            if timeout is not None:
                timeout -= _end - _start

    @abstractmethod
    def fileno(self) -> int:
        raise NotImplementedError
