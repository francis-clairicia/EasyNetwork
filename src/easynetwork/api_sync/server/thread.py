# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Asynchronous network server module"""

from __future__ import annotations

__all__ = [
    "StandaloneNetworkServerThread",
]

import threading as _threading
import time
from typing import Generic, TypeVar

from .abc import AbstractStandaloneNetworkServer

_ServerT = TypeVar("_ServerT", bound="AbstractStandaloneNetworkServer")


class StandaloneNetworkServerThread(_threading.Thread, Generic[_ServerT]):
    def __init__(
        self,
        server: _ServerT,
        group: None = None,
        name: str | None = None,
        *,
        daemon: bool | None = None,
    ) -> None:
        super().__init__(group=group, target=None, name=name, daemon=daemon)
        self.__server: _ServerT = server
        self.__is_up_event: _threading.Event = _threading.Event()

    def start(self) -> None:
        super().start()
        self.__is_up_event.wait()

    def run(self) -> None:
        return self.__server.serve_forever(is_up_event=self.__is_up_event)

    def join(self, timeout: float | None = None) -> None:
        _start = time.perf_counter()
        try:
            if self.is_alive():
                self.__server.shutdown(timeout=timeout)
        finally:
            _end = time.perf_counter()
            if timeout is not None:
                timeout -= _end - _start
            super().join(timeout=timeout)

    @property
    def server(self) -> _ServerT:
        return self.__server
