# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Network server request executors module"""

from __future__ import annotations

__all__ = ["SyncRequestExecutor"]

from typing import Any, Callable, TypeVar

from .abc import AbstractRequestExecutor

_RequestVar = TypeVar("_RequestVar")
_ClientVar = TypeVar("_ClientVar")


class SyncRequestExecutor(AbstractRequestExecutor):
    __slots__ = ()

    def execute(
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
