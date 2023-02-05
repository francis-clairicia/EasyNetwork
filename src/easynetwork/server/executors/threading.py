# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Network server request executors module"""

from __future__ import annotations

__all__ = ["ThreadingRequestExecutor"]

import concurrent.futures
import itertools
from typing import Callable, ParamSpec

from .abc import AbstractRequestExecutor

_P = ParamSpec("_P")


class ThreadingRequestExecutor(AbstractRequestExecutor):
    __slots__ = ("__pool",)

    __counter = itertools.count().__next__

    def __init__(self, *, max_workers: int | None = None, thread_name_prefix: str | None = None) -> None:
        super().__init__()
        if thread_name_prefix is None:
            thread_name_prefix = f"ThreadingRequestExecutor-{ThreadingRequestExecutor.__counter()}"
        self.__pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix=thread_name_prefix,
        )

    def execute(self, __request_handler: Callable[_P, None], /, *args: _P.args, **kwargs: _P.kwargs) -> None:
        self.__pool.submit(__request_handler, *args, **kwargs)

    def on_server_stop(self) -> None:
        super().on_server_stop()
        self.__pool.shutdown(wait=True, cancel_futures=False)

    def on_server_close(self) -> None:
        super().on_server_close()
        self.__pool.shutdown(wait=True, cancel_futures=True)
