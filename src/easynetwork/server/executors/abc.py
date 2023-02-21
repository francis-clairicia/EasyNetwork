# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Network server request executors module"""

from __future__ import annotations

__all__ = ["AbstractRequestExecutor", "RequestFuture"]

import concurrent.futures
from abc import ABCMeta, abstractmethod
from typing import Callable, ParamSpec

_P = ParamSpec("_P")


class RequestFuture(metaclass=ABCMeta):
    __slots__ = ("__fut",)

    def __init__(self, future: concurrent.futures.Future[None]) -> None:
        self.__fut: concurrent.futures.Future[None] = future

    def done(self) -> bool:
        return self.__fut.done()

    def add_done_callback(self, __cb: Callable[_P, object], /, *args: _P.args, **kwargs: _P.kwargs) -> None:
        def inner(future: concurrent.futures.Future[None]) -> None:
            del future  # Not needed
            __cb(*args, **kwargs)

        self.__fut.add_done_callback(inner)


class AbstractRequestExecutor(metaclass=ABCMeta):
    __slots__ = ("__weakref__",)

    @abstractmethod
    def execute(self, __request_handler: Callable[_P, None], /, *args: _P.args, **kwargs: _P.kwargs) -> RequestFuture:
        raise NotImplementedError

    def service_actions(self) -> None:
        pass

    def shutdown(self) -> None:
        pass
