# Copyright 2021-2024, Francis Clairicia-Rose-Claire-Josephine
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
"""Helper module for async backend"""

from __future__ import annotations

__all__ = [
    "BuiltinAsyncBackendToken",
    "ensure_backend",
]

from typing import Literal, TypeAlias, cast

from . import _sniffio_helpers
from .abc import AsyncBackend

BuiltinAsyncBackendToken: TypeAlias = Literal["asyncio"]


def ensure_backend(backend: AsyncBackend | BuiltinAsyncBackendToken | None) -> AsyncBackend:
    """
    TODO: Add docstring
    """
    if backend is None:
        backend = cast(BuiltinAsyncBackendToken, _sniffio_helpers.current_async_library())

    match backend:
        case "asyncio":
            from ...std_asyncio.backend import AsyncIOBackend

            return AsyncIOBackend()
        case AsyncBackend():
            return backend
        case str():
            raise NotImplementedError(backend)
        case _:
            raise TypeError(f"Expected either a string literal or a backend instance, got {backend!r}")
