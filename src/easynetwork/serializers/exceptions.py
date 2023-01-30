# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Network packet serializer exceptions definition module"""

from __future__ import annotations

__all__ = [
    "DeserializeError",
    "IncrementalDeserializeError",
]

from typing import Any


class DeserializeError(Exception):
    def __init__(self, message: str, error_info: Any = None) -> None:
        super().__init__(message)
        self.error_info: Any = error_info


class IncrementalDeserializeError(DeserializeError):
    def __init__(self, message: str, remaining_data: bytes, error_info: Any = None) -> None:
        super().__init__(message, error_info=error_info)
        self.remaining_data: bytes = remaining_data
