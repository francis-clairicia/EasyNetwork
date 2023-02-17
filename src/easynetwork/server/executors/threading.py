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
    __slots__ = ("__pool", "__block_on_close")

    __counter = itertools.count().__next__

    def __init__(
        self,
        *,
        max_workers: int | None = None,
        thread_name_prefix: str | None = None,
        block_on_close: bool = True,
    ) -> None:
        super().__init__()
        if thread_name_prefix is None:
            thread_name_prefix = f"ThreadingRequestExecutor-{ThreadingRequestExecutor.__counter()}"
        self.__pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix=thread_name_prefix,
        )
        self.__block_on_close: bool = bool(block_on_close)

    def execute(self, __request_handler: Callable[_P, None], /, *args: _P.args, **kwargs: _P.kwargs) -> None:
        self.__pool.submit(__request_handler, *args, **kwargs)

    def on_server_close(self) -> None:
        try:
            self.__pool.shutdown(wait=self.__block_on_close, cancel_futures=False)
        finally:
            super().on_server_close()
