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
    "AbstractAsyncBaseServerAdapter",
    "AbstractAsyncBaseSocketAdapter",
    "AbstractAsyncDatagramServerAdapter",
    "AbstractAsyncDatagramSocketAdapter",
    "AbstractAsyncServerAdapter",
    "AbstractAsyncStreamSocketAdapter",
    "ILock",
]

from abc import ABCMeta, abstractmethod
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Protocol, Sequence, TypeVar

if TYPE_CHECKING:
    import concurrent.futures
    import socket as _socket
    from types import TracebackType

    from _typeshed import ReadableBuffer

    from ...tools.socket import SocketProxy


_T = TypeVar("_T")


class ILock(Protocol):
    async def __aenter__(self) -> Any:  # pragma: no cover
        ...

    async def __aexit__(
        self,
        __exc_type: type[BaseException] | None,
        __exc_val: BaseException | None,
        __exc_tb: TracebackType | None,
        /,
    ) -> bool | None:  # pragma: no cover
        ...

    async def acquire(self) -> Any:  # pragma: no cover
        ...

    def release(self) -> None:  # pragma: no cover
        ...

    def locked(self) -> bool:  # pragma: no cover
        ...


class AbstractAsyncBaseSocketAdapter(metaclass=ABCMeta):
    __slots__ = ("__weakref__",)

    if TYPE_CHECKING:
        __Self = TypeVar("__Self", bound="AbstractAsyncBaseSocketAdapter")

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
    async def abort(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def getsockname(self) -> tuple[Any, ...]:
        raise NotImplementedError

    @abstractmethod
    def getpeername(self) -> tuple[Any, ...] | None:
        raise NotImplementedError

    @abstractmethod
    def proxy(self) -> SocketProxy:
        raise NotImplementedError

    @abstractmethod
    def get_backend(self) -> AbstractAsyncBackend:
        raise NotImplementedError


class AbstractAsyncStreamSocketAdapter(AbstractAsyncBaseSocketAdapter):
    __slots__ = ()

    @abstractmethod
    def getpeername(self) -> tuple[Any, ...]:
        raise NotImplementedError

    @abstractmethod
    async def recv(self, __bufsize: int, /) -> bytes:
        raise NotImplementedError

    @abstractmethod
    async def sendall(self, __data: ReadableBuffer, /) -> None:
        raise NotImplementedError


class AbstractAsyncDatagramSocketAdapter(AbstractAsyncBaseSocketAdapter):
    __slots__ = ()

    @abstractmethod
    async def recvfrom(self) -> tuple[bytes, tuple[Any, ...]]:
        raise NotImplementedError

    @abstractmethod
    async def sendto(self, __data: ReadableBuffer, __address: tuple[Any, ...] | None = ..., /) -> None:
        raise NotImplementedError


class AbstractAsyncBaseServerAdapter(metaclass=ABCMeta):
    __slots__ = ("__weakref__",)

    if TYPE_CHECKING:
        __Self = TypeVar("__Self", bound="AbstractAsyncBaseServerAdapter")

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
    async def close(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def is_serving(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def serve_forever(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_backend(self) -> AbstractAsyncBackend:
        raise NotImplementedError


class AbstractAsyncServerAdapter(AbstractAsyncBaseServerAdapter):
    __slots__ = ()

    @abstractmethod
    def stop_serving(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def sockets(self) -> Sequence[SocketProxy]:
        raise NotImplementedError


class AbstractAsyncDatagramServerAdapter(AbstractAsyncBaseServerAdapter):
    __slots__ = ()

    @abstractmethod
    async def sendto(self, __data: ReadableBuffer, __address: tuple[Any, ...], /) -> None:
        raise NotImplementedError

    @abstractmethod
    def socket(self) -> SocketProxy | None:
        raise NotImplementedError


class AbstractAsyncBackend(metaclass=ABCMeta):
    __slots__ = ("__weakref__",)

    @abstractmethod
    async def coro_yield(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def create_tcp_connection(
        self,
        host: str,
        port: int,
        *,
        family: int,
        source_address: tuple[str, int] | None,
        happy_eyeballs_delay: float | None,
    ) -> AbstractAsyncStreamSocketAdapter:
        raise NotImplementedError

    @abstractmethod
    async def wrap_tcp_socket(self, socket: _socket.socket) -> AbstractAsyncStreamSocketAdapter:
        raise NotImplementedError

    @abstractmethod
    async def create_tcp_server(
        self,
        client_connected_cb: Callable[[AbstractAsyncStreamSocketAdapter], Coroutine[Any, Any, Any]],
        host: str | Sequence[str],
        port: int,
        *,
        family: int,
        backlog: int | None,
        reuse_address: bool,
        reuse_port: bool,
    ) -> AbstractAsyncServerAdapter:
        raise NotImplementedError

    @abstractmethod
    async def create_udp_endpoint(
        self,
        *,
        family: int,
        local_address: tuple[str, int] | None,
        remote_address: tuple[str, int] | None,
        reuse_port: bool,
    ) -> AbstractAsyncDatagramSocketAdapter:
        raise NotImplementedError

    @abstractmethod
    async def wrap_udp_socket(self, socket: _socket.socket) -> AbstractAsyncDatagramSocketAdapter:
        raise NotImplementedError

    @abstractmethod
    async def create_udp_server(
        self,
        datagram_received_cb: Callable[[bytes, tuple[Any, ...]], Coroutine[Any, Any, Any]],
        error_received_cb: Callable[[Exception], Coroutine[Any, Any, Any]],
        host: str,
        port: int,
        *,
        family: int,
        reuse_port: bool,
    ) -> AbstractAsyncDatagramServerAdapter:
        raise NotImplementedError

    @abstractmethod
    def create_lock(self) -> ILock:
        raise NotImplementedError

    async def wait_future(self, future: concurrent.futures.Future[_T]) -> _T:
        while not future.done():
            await self.coro_yield()
        return future.result()
