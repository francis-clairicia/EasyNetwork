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

__all__ = ["AsyncBackendFactory", "current_async_backend"]

import functools
import threading
from collections import deque
from collections.abc import Callable
from typing import Final, final

from ....exceptions import UnsupportedOperation
from ... import _lock
from ..._final import runtime_final_class
from . import _sniffio_helpers
from .abc import AsyncBackend


@final
@runtime_final_class
class AsyncBackendFactory:
    __lock: Final[_lock.ForkSafeLock[threading.RLock]] = _lock.ForkSafeLock(threading.RLock)
    __hooks: Final[deque[Callable[[str], AsyncBackend]]] = deque()
    __instances: Final[dict[str, AsyncBackend]] = {}

    @classmethod
    def current(cls) -> AsyncBackend:
        name: str = _sniffio_helpers.current_async_library()
        return cls.__get_backend(name, "Running library {name!r} misses the backend implementation")

    @classmethod
    def get_backend(cls, name: str, /) -> AsyncBackend:
        return cls.__get_backend(name, "Unknown backend {name!r}")

    @classmethod
    def push_factory_hook(cls, factory: Callable[[str], AsyncBackend], /) -> None:
        if not callable(factory):
            raise TypeError(f"{factory!r} is not callable")
        with cls.__lock.get():
            cls.__hooks.appendleft(factory)

    @classmethod
    def push_backend_factory(cls, backend_name: str, factory: Callable[[], AsyncBackend]) -> None:
        if not isinstance(backend_name, str):
            raise TypeError("backend_name: Expected a string")
        if backend_name.strip() != backend_name or not backend_name:
            raise ValueError("backend_name: Invalid value")
        if not callable(factory):
            raise TypeError(f"{factory!r} is not callable")
        return cls.push_factory_hook(functools.partial(cls.__backend_factory_hook, backend_name, factory))

    @classmethod
    def invalidate_backends_cache(cls) -> None:
        with cls.__lock.get():
            cls.__instances.clear()

    @classmethod
    def remove_installed_hooks(cls) -> None:
        with cls.__lock.get():
            cls.__hooks.clear()

    @classmethod
    def __get_backend(cls, name: str, error_msg_format: str) -> AsyncBackend:
        with cls.__lock.get():
            try:
                return cls.__instances[name]
            except KeyError:
                pass

            backend_instance: AsyncBackend | None = None
            for factory_hook in cls.__hooks:
                try:
                    backend_instance = factory_hook(name)
                except UnsupportedOperation:
                    continue

                if not isinstance(backend_instance, AsyncBackend):
                    raise TypeError(f"{factory_hook!r} did not return an AsyncBackend instance")
                break

            if backend_instance is None and name == "asyncio":
                from ...std_asyncio import AsyncIOBackend

                backend_instance = AsyncIOBackend()

            if backend_instance is None:
                raise NotImplementedError(error_msg_format.format(name=name))

            cls.__instances[name] = backend_instance
            return backend_instance

    @staticmethod
    def __backend_factory_hook(backend_name: str, factory: Callable[[], AsyncBackend], name: str, /) -> AsyncBackend:
        if name != backend_name:
            raise UnsupportedOperation(f"{name!r} backend is not implemented")
        return factory()


current_async_backend = AsyncBackendFactory.current
