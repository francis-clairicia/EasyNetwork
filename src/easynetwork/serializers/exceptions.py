# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Network packet serializer exceptions definition module"""

from __future__ import annotations

__all__ = ["DeserializeError"]

from typing import Any


class DeserializeError(Exception):
    def __init__(self, message: str, error_info: Any = None) -> None:
        super().__init__(message)
        self.error_info: Any = error_info
