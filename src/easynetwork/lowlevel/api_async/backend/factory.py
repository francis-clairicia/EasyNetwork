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

from ... import _lock
from ..._final import runtime_final_class
from . import _sniffio_helpers
from .abc import AsyncBackend


@final
@runtime_final_class
class AsyncBackendFactory:
    __lock: Final[_lock.ForkSafeLock[threading.RLock]] = _lock.ForkSafeLock(threading.RLock)
    __hooks: Final[deque[Callable[[str], AsyncBackend | None]]] = deque()
    __instances: Final[dict[str, AsyncBackend]] = {}

    @classmethod
    def current(cls) -> AsyncBackend:
        name: str = _sniffio_helpers.current_async_library()
        return cls.__get_backend(name, error_msg_format="Running library {name!r} misses the backend implementation")

    @classmethod
    def get_backend(cls, name: str, /) -> AsyncBackend:
        return cls.__get_backend(name, error_msg_format="Unknown backend {name!r}")

    @classmethod
    def push_factory_hook(cls, factory: Callable[[str], AsyncBackend | None], /) -> None:
        if not callable(factory):
            raise TypeError(f"{factory!r} is not callable")
        with cls.__lock.get():
            if factory in cls.__hooks:
                raise ValueError(f"{factory!r} is already registered")
            cls.__hooks.appendleft(factory)
            cls.__instances.clear()

    @classmethod
    def remove_factory_hook(cls, factory: Callable[[str], AsyncBackend | None], /) -> None:
        with cls.__lock.get():
            try:
                cls.__hooks.remove(factory)
            except ValueError:
                pass
            else:
                cls.__instances.clear()

    @classmethod
    def backend_factory_hook(cls, backend_name: str, factory: Callable[[], AsyncBackend]) -> Callable[[str], AsyncBackend | None]:
        if not isinstance(backend_name, str):
            raise TypeError("backend_name: Expected a string")
        if backend_name.strip() != backend_name or not backend_name:
            raise ValueError("backend_name: Invalid value")
        if not callable(factory):
            raise TypeError(f"{factory!r} is not callable")
        return functools.partial(cls.__backend_factory_hook, backend_name, factory)

    @classmethod
    def __get_backend(cls, name: str, error_msg_format: str) -> AsyncBackend:
        with cls.__lock.get():
            try:
                return cls.__instances[name]
            except KeyError:
                pass

            backend_instance: AsyncBackend | None = None
            for factory_hook in cls.__hooks:
                backend_instance = factory_hook(name)
                if backend_instance is None:
                    continue
                if not isinstance(backend_instance, AsyncBackend):
                    raise TypeError(f"{factory_hook!r} did not return an AsyncBackend instance")
                break

            if backend_instance is None:
                match name:
                    case "asyncio":
                        from ...std_asyncio import AsyncIOBackend

                        backend_instance = AsyncIOBackend()
                    case _:
                        raise NotImplementedError(error_msg_format.format(name=name))

            cls.__instances[name] = backend_instance
            return backend_instance

    @staticmethod
    def __backend_factory_hook(backend_name: str, factory: Callable[[], AsyncBackend], name: str, /) -> AsyncBackend | None:
        if name != backend_name:
            return None
        instance = factory()
        if not isinstance(instance, AsyncBackend):
            raise TypeError(f"{factory!r} did not return an AsyncBackend instance")
        return instance


current_async_backend = AsyncBackendFactory.current
