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
"""Asynchronous backend engine factory module"""

from __future__ import annotations

__all__ = ["AsyncBackendFactory"]

import functools
import inspect
from collections import Counter
from collections.abc import Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final, final

from .abc import AsyncBackend
from .sniffio import current_async_library as _sniffio_current_async_library

if TYPE_CHECKING:
    from importlib.metadata import EntryPoint


@final
class AsyncBackendFactory:
    GROUP_NAME: Final[str] = "easynetwork.async.backends"
    __BACKEND: str | type[AsyncBackend] | None = None
    __BACKEND_EXTENSIONS: Final[dict[str, type[AsyncBackend]]] = {}

    @staticmethod
    def get_default_backend(guess_current_async_library: bool = True) -> type[AsyncBackend]:
        backend: str | type[AsyncBackend] | None = AsyncBackendFactory.__BACKEND
        if isinstance(backend, type):
            return backend
        if backend is None:
            if guess_current_async_library:
                backend = _sniffio_current_async_library()  # must raise if not recognized
            else:
                backend = "asyncio"
        return AsyncBackendFactory.__get_backend_cls(
            backend,
            "Running library {name!r} misses the backend implementation",
            extended=True,
        )

    @staticmethod
    def set_default_backend(backend: str | type[AsyncBackend] | None) -> None:
        match backend:
            case type() if not issubclass(backend, AsyncBackend) or inspect.isabstract(backend):
                raise TypeError(f"Invalid backend class: {backend!r}")
            case type() | None:
                pass
            case str():
                AsyncBackendFactory.__get_backend_cls(backend, extended=False)
            case _:  # pragma: no cover
                raise TypeError(f"Invalid argument: {backend!r}")

        AsyncBackendFactory.__BACKEND = backend

    @staticmethod
    def extend(backend_name: str, backend_cls: type[AsyncBackend] | None) -> None:
        default_backend_cls = AsyncBackendFactory.__get_backend_cls(backend_name, extended=False)
        if backend_cls is None or backend_cls is default_backend_cls:
            AsyncBackendFactory.__BACKEND_EXTENSIONS.pop(backend_name, None)
            return
        if not issubclass(backend_cls, default_backend_cls):
            raise TypeError(f"Invalid backend class (not a subclass of {default_backend_cls!r}): {backend_cls!r}")
        AsyncBackendFactory.__BACKEND_EXTENSIONS[backend_name] = backend_cls

    @staticmethod
    def new(backend: str | None = None, /, **kwargs: Any) -> AsyncBackend:
        backend_cls: type[AsyncBackend]
        if backend is None:
            backend_cls = AsyncBackendFactory.get_default_backend(guess_current_async_library=True)
        else:
            backend_cls = AsyncBackendFactory.__get_backend_cls(backend, extended=True)
        return backend_cls(**kwargs)

    @staticmethod
    def ensure(backend: str | AsyncBackend | None, kwargs: Mapping[str, Any] | None = None) -> AsyncBackend:
        if not isinstance(backend, AsyncBackend):
            if kwargs is None:
                kwargs = {}
            backend = AsyncBackendFactory.new(backend, **kwargs)
        return backend

    @staticmethod
    def get_all_backends(*, extended: bool = True) -> MappingProxyType[str, type[AsyncBackend]]:
        backends = {
            name: AsyncBackendFactory.__get_backend_cls(name, extended=extended)
            for name in AsyncBackendFactory.__get_available_backends()
        }
        return MappingProxyType(backends)

    @staticmethod
    def get_available_backends() -> frozenset[str]:
        return frozenset(AsyncBackendFactory.__get_available_backends())

    @staticmethod
    def remove_all_extensions() -> None:
        AsyncBackendFactory.__BACKEND_EXTENSIONS.clear()

    @staticmethod
    def invalidate_backends_cache() -> None:
        AsyncBackendFactory.remove_all_extensions()
        AsyncBackendFactory.__load_backend_cls_from_entry_point.cache_clear()
        AsyncBackendFactory.__get_available_backends.cache_clear()

    @staticmethod
    def __get_backend_cls(
        name: str,
        error_msg_format: str = "Unknown backend {name!r}",
        *,
        extended: bool,
    ) -> type[AsyncBackend]:
        if extended:
            try:
                return AsyncBackendFactory.__BACKEND_EXTENSIONS[name]
            except KeyError:
                pass
        try:
            return AsyncBackendFactory.__load_backend_cls_from_entry_point(name)
        except KeyError:
            raise KeyError(error_msg_format.format(name=name)) from None

    @staticmethod
    @functools.cache
    def __load_backend_cls_from_entry_point(name: str) -> type[AsyncBackend]:
        entry_point: EntryPoint = AsyncBackendFactory.__get_available_backends()[name]

        entry_point_cls: Any = entry_point.load()
        if (
            not isinstance(entry_point_cls, type)
            or not issubclass(entry_point_cls, AsyncBackend)
            or inspect.isabstract(entry_point_cls)
        ):
            raise TypeError(f"Invalid backend entry point (name={name!r}): {entry_point_cls!r}")
        return entry_point_cls

    @staticmethod
    @functools.cache
    def __get_available_backends() -> MappingProxyType[str, EntryPoint]:
        from importlib.metadata import EntryPoint, entry_points as get_all_entry_points

        entry_points = get_all_entry_points(group=AsyncBackendFactory.GROUP_NAME)
        duplicate_counter: Counter[str] = Counter([ep.name for ep in entry_points])

        if duplicates := {name for name in duplicate_counter if duplicate_counter[name] > 1}:
            raise TypeError(f"Conflicting backend name caught: {', '.join(map(repr, sorted(duplicates)))}")

        backends: dict[str, EntryPoint] = {ep.name: ep for ep in entry_points}

        if "asyncio" not in backends:
            from importlib.util import resolve_name

            backends["asyncio"] = EntryPoint(
                name="asyncio",
                value=f"{resolve_name('...asyncio', __package__)}:AsyncIOBackend",
                group=AsyncBackendFactory.GROUP_NAME,
            )

        return MappingProxyType(backends)
