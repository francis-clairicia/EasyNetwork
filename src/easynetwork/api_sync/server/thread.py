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
"""Asynchronous network server module"""

from __future__ import annotations

__all__ = [
    "StandaloneNetworkServerThread",
]

import threading as _threading
import time

from .abc import AbstractStandaloneNetworkServer


class StandaloneNetworkServerThread(_threading.Thread):
    def __init__(
        self,
        server: AbstractStandaloneNetworkServer,
        group: None = None,
        name: str | None = None,
        *,
        daemon: bool | None = None,
    ) -> None:
        super().__init__(group=group, target=None, name=name, daemon=daemon)
        self.__server: AbstractStandaloneNetworkServer | None = server
        self.__is_up_event: _threading.Event = _threading.Event()

    def start(self) -> None:
        super().start()
        self.__is_up_event.wait()

    def run(self) -> None:
        assert self.__server is not None, f"{self.__server=}"  # nosec assert_used
        try:
            return self.__server.serve_forever(is_up_event=self.__is_up_event)
        finally:
            self.__server = None
            self.__is_up_event.set()

    def join(self, timeout: float | None = None) -> None:
        server = self.__server
        if server is not None:
            _start = time.perf_counter()
            try:
                server.shutdown(timeout=timeout)
            finally:
                _end = time.perf_counter()
                if timeout is not None:
                    timeout -= _end - _start
                super().join(timeout=timeout)
        else:
            super().join(timeout=timeout)
