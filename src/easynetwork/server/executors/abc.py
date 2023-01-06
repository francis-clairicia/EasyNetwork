# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Network server request executors module"""

from __future__ import annotations

__all__ = ["AbstractRequestExecutor"]

from abc import ABCMeta, abstractmethod
from typing import Any, Callable, TypeVar

_RequestVar = TypeVar("_RequestVar")
_ClientVar = TypeVar("_ClientVar")


class AbstractRequestExecutor(metaclass=ABCMeta):
    __slots__ = ("__weakref__",)

    @abstractmethod
    def execute(
        self,
        request_handler: Callable[[_RequestVar, _ClientVar], None],
        request_teardown: tuple[Callable[[_ClientVar, dict[str, Any]], None], dict[str, Any] | None] | None,
        request: _RequestVar,
        client: _ClientVar,
        error_handler: Callable[[_ClientVar], None],
    ) -> None:
        raise NotImplementedError

    def service_actions(self) -> None:
        pass

    def on_server_close(self) -> None:
        pass
