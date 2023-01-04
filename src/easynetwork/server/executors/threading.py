# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Network server request executors module"""

from __future__ import annotations

__all__ = ["ThreadingRequestExecutor"]

from threading import Thread
from typing import Any, Callable, TypeVar

from .abc import AbstractRequestExecutor

_RequestVar = TypeVar("_RequestVar")
_ClientVar = TypeVar("_ClientVar")


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

    def process_request_thread(
        self,
        request_handler: Callable[[_RequestVar, _ClientVar], None],
        request_teardown: Callable[[_ClientVar, dict[str, Any]], None] | None,
        request_context: dict[str, Any] | None,
        request: _RequestVar,
        client: _ClientVar,
        error_handler: Callable[[_ClientVar], None],
    ) -> None:
        try:
            request_handler(request, client)
        except Exception:
            error_handler(client)
        finally:
            try:
                if request_teardown is not None:
                    request_teardown(client, request_context or {})
            except Exception:
                error_handler(client)

    def execute(
        self,
        request_handler: Callable[[_RequestVar, _ClientVar], None],
        request_teardown: Callable[[_ClientVar, dict[str, Any]], None] | None,
        request_context: dict[str, Any] | None,
        request: _RequestVar,
        client: _ClientVar,
        error_handler: Callable[[_ClientVar], None],
    ) -> None:
        kwargs = {k: v for k, v in locals().items() if k != "self"}

        threads: _Threads | None = self.__threads
        t = Thread(target=self.process_request_thread, kwargs=kwargs)
        t.daemon = self.__daemon_threads
        if threads is not None:
            threads.append(t)
        t.start()

    def on_server_close(self) -> None:
        super().on_server_close()
        if self.__threads:
            self.__threads.join()
