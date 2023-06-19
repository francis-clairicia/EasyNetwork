# -*- coding: utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""
Asynchronous client/server module
"""

from __future__ import annotations

__all__ = ["current_async_library", "current_async_library_cvar"]

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from contextvars import ContextVar


current_async_library_cvar: ContextVar[str | None] | None

try:
    import sniffio

    def current_async_library() -> str:
        return sniffio.current_async_library()

except ImportError:

    def current_async_library() -> str:
        return "asyncio"


try:
    from sniffio import current_async_library_cvar
except ImportError:
    current_async_library_cvar = None
