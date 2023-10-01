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
"""Low-level transports module"""

from __future__ import annotations

__all__ = [
    "BaseTransport",
    "DatagramTransport",
    "StreamTransport",
]

import time
from abc import ABCMeta, abstractmethod
from collections.abc import Iterable
from typing import Any


class BaseTransport(metaclass=ABCMeta):
    """
    Base class for a data transport.
    """

    __slots__ = ("__weakref__",)

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def is_closed(self) -> bool:
        raise NotImplementedError

    def get_extra_info(self, name: str, default: Any = None) -> Any:
        return default


class StreamTransport(BaseTransport):
    __slots__ = ()

    @abstractmethod
    def recv(self, bufsize: int, timeout: float) -> bytes:
        raise NotImplementedError

    @abstractmethod
    def send(self, data: bytes | bytearray | memoryview, timeout: float) -> int:
        raise NotImplementedError

    @abstractmethod
    def send_eof(self) -> None:
        raise NotImplementedError

    def send_all(self, data: bytes | bytearray | memoryview, timeout: float) -> None:
        perf_counter = time.perf_counter  # pull function to local namespace
        total_sent: int = 0
        with memoryview(data) as data:
            nb_bytes_to_send = len(data)
            if nb_bytes_to_send == 0:
                self.send(data, timeout)
                return
            while total_sent < nb_bytes_to_send:
                with data[total_sent:] as buffer:
                    _start = perf_counter()
                    sent: int = self.send(buffer, timeout)
                    _end = perf_counter()
                if sent < 0:
                    raise RuntimeError("transport.send() returned a negative value")
                total_sent += sent
                timeout -= _end - _start

    def send_all_from_iterable(self, iterable_of_data: Iterable[bytes | bytearray | memoryview], timeout: float) -> None:
        data = b"".join(iterable_of_data)
        return self.send_all(data, timeout)


class DatagramTransport(BaseTransport):
    __slots__ = ()

    @abstractmethod
    def recv(self, timeout: float) -> bytes:
        raise NotImplementedError

    @abstractmethod
    def send(self, data: bytes | bytearray | memoryview, timeout: float) -> None:
        raise NotImplementedError
