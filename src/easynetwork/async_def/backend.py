# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""
Asynchronous client/server module
"""

from __future__ import annotations

__all__ = [
    "AbstractAsyncBackend",
    "AbstractBaseAsyncSocketAdapter",
    "AbstractDatagramSocketAdapter",
    "AbstractStreamSocketAdapter",
    "AsyncBackendFactory",
    "CUSTOM_BACKEND_NAME",
]

import functools
from abc import ABCMeta, abstractmethod
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal, TypeVar, final

if TYPE_CHECKING:
    import socket as _socket
    from socket import _Address, _RetAddress
    from types import TracebackType

    from _typeshed import ReadableBuffer

    from ..tools.socket import SocketProxy


class AbstractBaseAsyncSocketAdapter(metaclass=ABCMeta):
    __slots__ = ("__weakref__",)

    if TYPE_CHECKING:
        __Self = TypeVar("__Self", bound="AbstractBaseAsyncSocketAdapter")

    async def __aenter__(self: __Self) -> __Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.close()

    @abstractmethod
    def is_closing(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def proxy(self) -> SocketProxy:
        raise NotImplementedError

    @abstractmethod
    def get_backend(self) -> AbstractAsyncBackend:
        raise NotImplementedError


class AbstractStreamSocketAdapter(AbstractBaseAsyncSocketAdapter):
    __slots__ = ()

    @abstractmethod
    async def recv(self, __bufsize: int, /) -> bytes:
        raise NotImplementedError

    @abstractmethod
    async def sendall(self, __data: ReadableBuffer, /) -> None:
        raise NotImplementedError


class AbstractDatagramSocketAdapter(AbstractBaseAsyncSocketAdapter):
    __slots__ = ()

    @abstractmethod
    async def recvfrom(self) -> tuple[bytes, _RetAddress]:
        raise NotImplementedError

    @abstractmethod
    async def sendto(self, __data: ReadableBuffer, __address: _Address | None = ..., /) -> None:
        raise NotImplementedError


class AbstractAsyncBackend(metaclass=ABCMeta):
    __slots__ = ("__weakref__",)

    def get_extra_info(self, key: str, default: Any = None) -> Any:
        return default

    @abstractmethod
    async def sleep(self, delay_in_seconds: float, /) -> None:
        raise NotImplementedError

    @abstractmethod
    async def create_tcp_connection(
        self,
        host: str,
        port: int,
        *,
        source_address: tuple[str, int] | None = ...,
        happy_eyeballs_delay: float | None = ...,
    ) -> AbstractStreamSocketAdapter:
        raise NotImplementedError

    @abstractmethod
    async def wrap_tcp_socket(self, socket: _socket.socket) -> AbstractStreamSocketAdapter:
        raise NotImplementedError

    @abstractmethod
    async def create_udp_endpoint(
        self,
        *,
        local_address: tuple[str, int] | None = ...,
        remote_address: tuple[str, int] | None = ...,
        reuse_port: bool = ...,
    ) -> AbstractDatagramSocketAdapter:
        raise NotImplementedError

    @abstractmethod
    async def wrap_udp_socket(self, socket: _socket.socket) -> AbstractDatagramSocketAdapter:
        raise NotImplementedError


CUSTOM_BACKEND_NAME: Literal["__custom__"] = "__custom__"


@final
class AsyncBackendFactory:
    __GROUP_NAME: str = "easynetwork.async.backends"
    __BACKEND: str | None = None
    __CUSTOM_BACKEND: dict[str, type[AbstractAsyncBackend]] = {}

    @staticmethod
    def get_default_backend(guess_current_async_library: bool = True) -> str:
        backend = AsyncBackendFactory.__BACKEND
        if backend is None:
            try:
                if not guess_current_async_library:
                    raise ModuleNotFoundError

                import sniffio
            except ModuleNotFoundError:
                backend = "asyncio"
            else:
                try:
                    backend = sniffio.current_async_library()
                except sniffio.AsyncLibraryNotFoundError:  # not running or unknown, fallback to 'asyncio'
                    backend = "asyncio"
                else:
                    if backend not in AsyncBackendFactory.__get_available_backends():
                        raise KeyError(f"Running library {backend!r} misses the backend implementation")
        return backend

    @staticmethod
    def set_default_backend(backend: str | type[AbstractAsyncBackend] | None) -> None:
        if isinstance(backend, type):
            if not issubclass(backend, AbstractAsyncBackend):
                raise TypeError(f"Invalid backend class: {backend!r}")
            AsyncBackendFactory.__CUSTOM_BACKEND[CUSTOM_BACKEND_NAME] = backend
            backend = CUSTOM_BACKEND_NAME
        else:
            if backend is None:
                AsyncBackendFactory.__CUSTOM_BACKEND.pop(CUSTOM_BACKEND_NAME, None)
            elif backend not in AsyncBackendFactory.__get_available_backends():
                raise KeyError(f"Unknown backend {backend!r}")
        AsyncBackendFactory.__BACKEND = backend

    @staticmethod
    def new(__backend: str | None = None, /, **kwargs: Any) -> AbstractAsyncBackend:
        backend_cls: type[AbstractAsyncBackend]
        if __backend is None:
            __backend = AsyncBackendFactory.get_default_backend(guess_current_async_library=True)
        backend_cls = AsyncBackendFactory.__get_available_backends()[__backend]
        return backend_cls(**kwargs)

    @staticmethod
    def get_available_backends() -> frozenset[str]:
        return frozenset(AsyncBackendFactory.__get_available_backends())

    @staticmethod
    @functools.cache
    def __get_available_backends() -> MappingProxyType[str, type[AbstractAsyncBackend]]:
        from collections import ChainMap, Counter
        from importlib.metadata import entry_points

        backends: dict[str, type[AbstractAsyncBackend]] = {}
        invalid_backends: set[str] = set()
        duplicate_counter: Counter[str] = Counter()

        for entry_point in entry_points(group=AsyncBackendFactory.__GROUP_NAME):
            entry_point_name = entry_point.name.strip()
            if not entry_point_name or entry_point_name == CUSTOM_BACKEND_NAME:
                invalid_backends.add(entry_point_name)
                continue
            duplicate_counter[entry_point_name] += 1
            if duplicate_counter[entry_point_name] > 1:
                continue
            entry_point_cls: Any = entry_point.load()
            if not isinstance(entry_point_cls, type) or not issubclass(entry_point_cls, AbstractAsyncBackend):
                invalid_backends.add(entry_point_name)
                continue
            backends[entry_point_name] = entry_point_cls

        if invalid_backends:
            raise TypeError(f"Invalid backend entry-points: {', '.join(map(repr, sorted(invalid_backends)))}")
        if duplicates := set(name for name in duplicate_counter if duplicate_counter[name] > 1):
            raise TypeError(f"Conflicting backend name caught: {', '.join(map(repr, sorted(duplicates)))}")

        assert "asyncio" in backends, "SystemError: Missing 'asyncio' entry point."

        return MappingProxyType(ChainMap(AsyncBackendFactory.__CUSTOM_BACKEND, backends))
