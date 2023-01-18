# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Network server request executors module"""

from __future__ import annotations

__all__ = ["AbstractRequestExecutor"]

from abc import ABCMeta, abstractmethod
from typing import Callable, ParamSpec

_P = ParamSpec("_P")


class AbstractRequestExecutor(metaclass=ABCMeta):
    __slots__ = ("__weakref__",)

    @abstractmethod
    def execute(self, __request_handler: Callable[_P, None], /, *args: _P.args, **kwargs: _P.kwargs) -> None:
        raise NotImplementedError

    def service_actions(self) -> None:
        pass

    def on_server_stop(self) -> None:
        pass

    def on_server_close(self) -> None:
        pass
