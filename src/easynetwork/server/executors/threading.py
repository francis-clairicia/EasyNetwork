# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Network server request executors module"""

from __future__ import annotations

__all__ = ["ThreadingRequestExecutor"]

from threading import Thread
from typing import Callable, ParamSpec

from .abc import AbstractRequestExecutor

_P = ParamSpec("_P")


class _Threads(list[Thread]):
    """
    Joinable list of all non-daemon threads.
    """

    def append(self, thread: Thread) -> None:
        self.reap()
        if thread.daemon:
            return
        super().append(thread)

    def pop_all(self) -> list[Thread]:
        self[:], result = [], self[:]
        return result

    def join(self) -> None:
        for thread in self.pop_all():
            thread.join()

    def reap(self) -> None:
        self[:] = (thread for thread in self if thread.is_alive())


class ThreadingRequestExecutor(AbstractRequestExecutor):
    __slots__ = ("__threads", "__daemon_threads")

    def __init__(self, *, daemon_threads: bool = False, block_on_close: bool = True) -> None:
        super().__init__()
        self.__threads: _Threads | None = _Threads() if block_on_close else None
        self.__daemon_threads: bool = bool(daemon_threads)

    def execute(self, __request_handler: Callable[_P, None], /, *args: _P.args, **kwargs: _P.kwargs) -> None:
        threads: _Threads | None = self.__threads
        t = Thread(target=__request_handler, args=args, kwargs=kwargs)
        t.daemon = self.__daemon_threads
        if threads is not None:
            threads.append(t)
        t.start()

    def on_server_close(self) -> None:
        super().on_server_close()
        if self.__threads:
            self.__threads.join()
