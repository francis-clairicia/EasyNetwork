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

__all__ = ["current_async_library", "setup_sniffio_contextvar"]

import contextvars
import sys


def current_async_library() -> str:
    try:
        from sniffio import current_async_library
    except ModuleNotFoundError:
        current_async_library = _current_async_library_fallback
    return current_async_library()


def _current_async_library_fallback() -> str:
    if "asyncio" in sys.modules:
        import asyncio

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            return "asyncio"
    raise RuntimeError("unknown async library, or not in async context")


def setup_sniffio_contextvar(context: contextvars.Context, library_name: str | None, /) -> None:
    try:
        import sniffio
    except ModuleNotFoundError:
        pass
    else:
        context.run(sniffio.current_async_library_cvar.set, library_name)
