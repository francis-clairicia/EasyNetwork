# Copyright 2021-2023, Francis Clairicia-Rose-Claire-Josephine
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
#
"""Helper module for sniffio integration"""

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
