# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""
Asynchronous client/server module
"""

from __future__ import annotations

__all__ = []  # type: list[str]

import functools
from abc import ABCMeta, abstractmethod
from types import MappingProxyType
from typing import TYPE_CHECKING, TypeVar, final

from ..tools.socket import SocketProxy

if TYPE_CHECKING:
    import socket as _socket
    from socket import _Address, _RetAddress
    from types import TracebackType

    from _typeshed import ReadableBuffer


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
        self.close()
        await self.wait_closed()

    @abstractmethod
    def is_closing(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def wait_closed(self) -> None:
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

    @abstractmethod
    async def create_tcp_connection(
        self,
        host: str,
        port: int,
        *,
        family: int = ...,
        proto: int = ...,
        source_address: tuple[str, int] | None = ...,
    ) -> AbstractStreamSocketAdapter:
        raise NotImplementedError

    @abstractmethod
    async def wrap_tcp_socket(self, socket: _socket.socket) -> AbstractStreamSocketAdapter:
        raise NotImplementedError

    @abstractmethod
    async def create_udp_endpoint(
        self,
        local_address: tuple[str, int] | None = ...,
        remote_address: tuple[str, int] | None = ...,
        reuse_port: bool = ...,
    ) -> AbstractDatagramSocketAdapter:
        raise NotImplementedError

    @abstractmethod
    async def wrap_udp_socket(self, socket: _socket.socket) -> AbstractDatagramSocketAdapter:
        raise NotImplementedError


@final
class AsyncBackendFactory:
    __BACKEND: str | None = None

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
    def set_default_backend(backend: str | None) -> None:
        if backend is not None and backend not in AsyncBackendFactory.__get_available_backends():
            raise KeyError(f"Unknown backend {backend!r}")
        AsyncBackendFactory.__BACKEND = backend

    @staticmethod
    def new(backend: str | None = None) -> AbstractAsyncBackend:
        if backend is None:
            backend = AsyncBackendFactory.get_default_backend(guess_current_async_library=True)
        backend_cls: type[AbstractAsyncBackend] = AsyncBackendFactory.__get_available_backends()[backend]
        return backend_cls()

    @staticmethod
    def get_available_backends() -> frozenset[str]:
        return frozenset(AsyncBackendFactory.__get_available_backends())

    @staticmethod
    @functools.cache
    def __get_available_backends() -> MappingProxyType[str, type[AbstractAsyncBackend]]:
        import inspect
        from importlib.metadata import entry_points

        backends = {e.name.strip(): e.load() for e in entry_points(group="easynetwork.asyncio.backends")}

        invalid_backends = set(
            name
            for name, value in backends.items()
            if not name or not inspect.isclass(value) or not issubclass(value, AbstractAsyncBackend)
        )
        if invalid_backends:
            raise ValueError(f"Invalid backends: {', '.join(map(repr, sorted(invalid_backends)))}")

        assert "asyncio" in backends

        return MappingProxyType(backends)
