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
]

import functools
from abc import ABCMeta, abstractmethod
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final, Protocol, TypeVar, final

if TYPE_CHECKING:
    import socket as _socket
    from socket import _Address, _RetAddress
    from types import TracebackType

    from _typeshed import ReadableBuffer

    from ..tools.socket import SocketProxy


class ILock(Protocol):
    async def __aenter__(self) -> Any:
        ...

    async def __aexit__(
        self,
        __exc_type: type[BaseException] | None,
        __exc_val: BaseException | None,
        __exc_tb: TracebackType | None,
        /,
    ) -> None:
        ...

    async def acquire(self) -> Any:
        ...

    def release(self) -> None:
        ...

    def locked(self) -> bool:
        ...


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

    def get_extra_info(self, name: str, default: Any = None) -> Any:
        return default

    @abstractmethod
    async def coro_yield(self) -> None:
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

    @abstractmethod
    def create_lock(self) -> ILock:
        raise NotImplementedError


@final
class AsyncBackendFactory:
    __GROUP_NAME: Final[str] = "easynetwork.async.backends"
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
            if not issubclass(backend, AbstractAsyncBackend):
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
    def get_available_backends() -> frozenset[str]:
        return frozenset(AsyncBackendFactory.__get_available_backends())

    @staticmethod
    def get_backend_cls(name: str) -> type[AbstractAsyncBackend]:
        return AsyncBackendFactory.__get_backend_cls(name)

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
        from collections import Counter
        from importlib.metadata import entry_points

        backends: dict[str, type[AbstractAsyncBackend]] = {}
        invalid_backends: set[str] = set()
        duplicate_counter: Counter[str] = Counter()

        for entry_point in entry_points(group=AsyncBackendFactory.__GROUP_NAME):
            entry_point_name = entry_point.name.strip()
            if not entry_point_name:
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

        return MappingProxyType(backends)
