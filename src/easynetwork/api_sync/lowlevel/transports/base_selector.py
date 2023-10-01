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
    "SelectorBaseTransport",
    "SelectorDatagramTransport",
    "SelectorStreamTransport",
]

import errno as _errno
import math
import selectors
import time
from abc import abstractmethod
from collections.abc import Callable
from typing import TypeVar

from ....tools._utils import error_from_errno as _error_from_errno, validate_timeout_delay as _validate_timeout_delay
from .abc import BaseTransport, DatagramTransport, StreamTransport

_R = TypeVar("_R")


class WouldBlockOnRead(Exception):
    pass


class WouldBlockOnWrite(Exception):
    pass


class SelectorBaseTransport(BaseTransport):
    __slots__ = (
        "__retry_interval",
        "__selector_factory",
    )

    def __init__(self, retry_interval: float, selector_factory: Callable[[], selectors.BaseSelector] | None = None) -> None:
        super().__init__()

        if selector_factory is None:
            selector_factory = getattr(selectors, "PollSelector", selectors.SelectSelector)
        self.__selector_factory: Callable[[], selectors.BaseSelector] = selector_factory

        self.__retry_interval: float = _validate_timeout_delay(retry_interval, positive_check=False)
        if self.__retry_interval <= 0:
            raise ValueError("retry_interval must be a strictly positive float")

    @abstractmethod
    def fileno(self) -> int:
        raise NotImplementedError

    def wait_readable(self, timeout: float) -> bool:
        return self.__poll(selectors.EVENT_READ, timeout)

    def wait_writable(self, timeout: float) -> bool:
        return self.__poll(selectors.EVENT_WRITE, timeout)

    def _retry(
        self,
        callback: Callable[[], _R],
        timeout: float,
    ) -> _R:
        perf_counter = time.perf_counter  # pull function to local namespace
        timeout = _validate_timeout_delay(timeout, positive_check=True)
        retry_interval = self.__retry_interval
        event: int
        with self.__selector_factory() as selector:
            while True:
                try:
                    return callback()
                except WouldBlockOnRead:
                    event = selectors.EVENT_READ
                except WouldBlockOnWrite:
                    event = selectors.EVENT_WRITE
                if timeout <= 0:
                    break
                is_retry_interval: bool
                wait_time: float
                if timeout <= retry_interval:
                    is_retry_interval = False
                    wait_time = timeout
                else:
                    is_retry_interval = True
                    wait_time = retry_interval
                available: bool
                try:
                    selector_key = selector.register(self.fileno(), event)
                except ValueError as exc:
                    raise _error_from_errno(_errno.EBADF) from exc
                try:
                    if wait_time == math.inf:
                        ready_list = selector.select()
                        if not ready_list:
                            raise RuntimeError("timeout error with infinite timeout")
                    else:
                        _start = perf_counter()
                        try:
                            ready_list = selector.select(wait_time)
                        finally:
                            _end = perf_counter()
                            timeout -= _end - _start
                except (OSError, ValueError):
                    # There will be a OSError when using this file descriptor afterward.
                    available = True
                else:
                    available = bool(ready_list)
                    del ready_list
                finally:
                    selector.unregister(selector_key.fileobj)
                    del selector_key
                if not available:
                    if not is_retry_interval:
                        break
        raise _error_from_errno(_errno.ETIMEDOUT)

    def __poll(self, events: int, timeout: float) -> bool:
        with self.__selector_factory() as selector:
            try:
                selector.register(self.fileno(), events)
            except ValueError as exc:
                raise _error_from_errno(_errno.EBADF) from exc
            try:
                if timeout == math.inf:
                    ready_list = selector.select()
                else:
                    ready_list = selector.select(timeout)
            except (OSError, ValueError):
                # There will be a OSError when using this file descriptor afterward.
                return True
            return bool(ready_list)


class SelectorStreamTransport(SelectorBaseTransport, StreamTransport):
    __slots__ = ()

    @abstractmethod
    def send_noblock(self, data: bytes | bytearray | memoryview) -> int:
        raise NotImplementedError

    @abstractmethod
    def recv_noblock(self, bufsize: int) -> bytes:
        raise NotImplementedError

    def send(self, data: bytes | bytearray | memoryview, timeout: float) -> int:
        return self._retry(lambda: self.send_noblock(data), timeout)

    def recv(self, bufsize: int, timeout: float) -> bytes:
        return self._retry(lambda: self.recv_noblock(bufsize), timeout)


class SelectorDatagramTransport(SelectorBaseTransport, DatagramTransport):
    __slots__ = ()

    @abstractmethod
    def send_noblock(self, data: bytes | bytearray | memoryview) -> None:
        raise NotImplementedError

    @abstractmethod
    def recv_noblock(self) -> bytes:
        raise NotImplementedError

    def send(self, data: bytes | bytearray | memoryview, timeout: float) -> None:
        return self._retry(lambda: self.send_noblock(data), timeout)

    def recv(self, timeout: float) -> bytes:
        return self._retry(self.recv_noblock, timeout)
