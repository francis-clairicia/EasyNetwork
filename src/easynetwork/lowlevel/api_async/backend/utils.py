# Copyright 2021-2025, Francis Clairicia-Rose-Claire-Josephine
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
"""Helper module for async backend."""

from __future__ import annotations

__all__ = [
    "BuiltinAsyncBackendLiteral",
    "ensure_backend",
    "new_builtin_backend",
]

from typing import Literal, TypeAlias, assert_never, cast

import sniffio

from .abc import AsyncBackend

BuiltinAsyncBackendLiteral: TypeAlias = Literal["asyncio", "trio"]
"""Supported asynchronous framework names."""


def new_builtin_backend(name: BuiltinAsyncBackendLiteral) -> AsyncBackend:
    """
    Obtain an interface for the given `backend`.

    Here is the list of the supported libraries:

    * ``"asyncio"``

    * ``"trio"``
    """
    match name:
        case "asyncio":
            from ._asyncio.backend import AsyncIOBackend

            return AsyncIOBackend()
        case "trio":
            from ._trio.backend import TrioBackend

            return TrioBackend()
        case str():
            raise NotImplementedError(name)
        case _:  # pragma: no cover
            assert_never(name)


def ensure_backend(backend: AsyncBackend | BuiltinAsyncBackendLiteral | None) -> AsyncBackend:
    """
    Obtain an interface for the given `backend`.

    * If `backend` is already an :class:`.AsyncBackend`, this object is returned.

    * If `backend` is a string token and matches one of the built-in implementation, a new object is returned.

       * See also :func:`new_builtin_backend`.

    * If :data:`None`, the function tries to guess the library currently used with :mod:`sniffio`.

    Raises:
        NotImplementedError: the current asynchronous library is not implemented.
        RuntimeError: unknown async library, or not in async context
    """
    if backend is None:
        backend = cast(BuiltinAsyncBackendLiteral, sniffio.current_async_library())

    match backend:
        case AsyncBackend():
            return backend
        case str():
            return new_builtin_backend(backend)
        case _:
            raise TypeError(f"Expected either a string literal or a backend instance, got {backend!r}")
