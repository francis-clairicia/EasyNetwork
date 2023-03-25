# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""
Asynchronous client/server module
"""

from __future__ import annotations

__all__ = ["AsyncBackendFactory"]

import functools
from types import MappingProxyType
from typing import Any, Final, final

from .abc import AbstractAsyncBackend


@final
class AsyncBackendFactory:
    GROUP_NAME: Final[str] = "easynetwork.async.backends"
    __BACKEND: type[AbstractAsyncBackend] | None = None

    @staticmethod
    def get_default_backend(guess_current_async_library: bool = True) -> type[AbstractAsyncBackend]:
        backend: type[AbstractAsyncBackend] | None = AsyncBackendFactory.__BACKEND
        if backend is None:
            _async_library: str
            try:
                if not guess_current_async_library:
                    raise ModuleNotFoundError

                import sniffio
            except ModuleNotFoundError:
                _async_library = "asyncio"
            else:
                _async_library = sniffio.current_async_library()  # must raise if not recognized
            backend = AsyncBackendFactory.__get_backend_cls(
                _async_library,
                "Running library {name!r} misses the backend implementation",
            )
        return backend

    @staticmethod
    def set_default_backend(backend: str | type[AbstractAsyncBackend] | None) -> None:
        if isinstance(backend, type):
            import inspect

            if not issubclass(backend, AbstractAsyncBackend) or inspect.isabstract(backend):
                raise TypeError(f"Invalid backend class: {backend!r}")
        elif backend is not None:
            backend = AsyncBackendFactory.__get_backend_cls(backend)
        AsyncBackendFactory.__BACKEND = backend

    @staticmethod
    def new(__backend: str | None = None, /, **kwargs: Any) -> AbstractAsyncBackend:
        backend_cls: type[AbstractAsyncBackend]
        if __backend is None:
            backend_cls = AsyncBackendFactory.get_default_backend(guess_current_async_library=True)
        else:
            backend_cls = AsyncBackendFactory.__get_backend_cls(__backend)
        return backend_cls(**kwargs)

    @staticmethod
    def get_available_backends() -> MappingProxyType[str, type[AbstractAsyncBackend]]:
        return AsyncBackendFactory.__get_available_backends()

    @staticmethod
    def invalidate_backends_cache() -> None:
        AsyncBackendFactory.__get_available_backends.cache_clear()

    @staticmethod
    def __get_backend_cls(name: str, error_msg_format: str = "Unknown backend {name!r}") -> type[AbstractAsyncBackend]:
        try:
            return AsyncBackendFactory.__get_available_backends()[name]
        except KeyError:
            raise KeyError(error_msg_format.format(name=name)) from None

    @staticmethod
    @functools.cache
    def __get_available_backends() -> MappingProxyType[str, type[AbstractAsyncBackend]]:
        import inspect
        from collections import Counter
        from importlib.metadata import entry_points

        backends: dict[str, type[AbstractAsyncBackend]] = {}
        invalid_backends: set[str] = set()
        duplicate_counter: Counter[str] = Counter()

        for entry_point in entry_points(group=AsyncBackendFactory.GROUP_NAME):
            entry_point_name = entry_point.name.strip()
            if not entry_point_name:
                invalid_backends.add(entry_point_name)
                continue
            duplicate_counter[entry_point_name] += 1
            if duplicate_counter[entry_point_name] > 1:
                continue
            entry_point_cls: Any = entry_point.load()
            if (
                not isinstance(entry_point_cls, type)
                or not issubclass(entry_point_cls, AbstractAsyncBackend)
                or inspect.isabstract(entry_point_cls)
            ):
                invalid_backends.add(entry_point_name)
                continue
            backends[entry_point_name] = entry_point_cls

        if invalid_backends:
            raise TypeError(f"Invalid backend entry points: {', '.join(map(repr, sorted(invalid_backends)))}")
        if duplicates := set(name for name in duplicate_counter if duplicate_counter[name] > 1):
            raise TypeError(f"Conflicting backend name caught: {', '.join(map(repr, sorted(duplicates)))}")

        assert "asyncio" in backends, "SystemError: Missing 'asyncio' entry point."

        return MappingProxyType(backends)
