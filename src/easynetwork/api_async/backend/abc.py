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
    "AbstractAsyncBaseSocketAdapter",
    "AbstractAsyncDatagramSocketAdapter",
    "AbstractAsyncListenerSocketAdapter",
    "AbstractAsyncStreamSocketAdapter",
    "AbstractTaskGroup",
    "ILock",
    "ITask",
]

from abc import ABCMeta, abstractmethod
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Protocol, Self, Sequence, TypeVar

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


class ITask(Protocol):
    def get_name(self) -> str:  # pragma: no cover
        ...

    def get_coro(self) -> Coroutine[Any, Any, Any]:  # pragma: no cover
        ...

    def done(self) -> bool:  # pragma: no cover
        ...

    def cancel(self) -> None:  # pragma: no cover
        ...


class AbstractTaskGroup(metaclass=ABCMeta):
    __slots__ = ("__weakref__",)

    @abstractmethod
    async def __aenter__(self) -> Self:
        raise NotImplementedError

    @abstractmethod
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        raise NotImplementedError

    @abstractmethod
    async def start(self, func: Callable[..., Coroutine[Any, Any, Any]], *args: Any, name: str | None = ...) -> ITask:
        ...

    @abstractmethod
    def start_soon(self, func: Callable[..., Coroutine[Any, Any, Any]], *args: Any, name: str | None = ...) -> None:
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


class AbstractAsyncListenerSocketAdapter(AbstractAsyncBaseSocketAdapter):
    __slots__ = ()

    @abstractmethod
    def getpeername(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def accept(self) -> tuple[AbstractAsyncStreamSocketAdapter, tuple[Any, ...]]:
        raise NotImplementedError


class AbstractAsyncBackend(metaclass=ABCMeta):
    __slots__ = ("__weakref__",)

    @abstractmethod
    async def coro_yield(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def create_task_group(self) -> AbstractTaskGroup:
        raise NotImplementedError

    @abstractmethod
    async def create_tcp_connection(
        self,
        host: str,
        port: int,
        *,
        family: int,
        local_address: tuple[str, int] | None,
        happy_eyeballs_delay: float | None,
    ) -> AbstractAsyncStreamSocketAdapter:
        raise NotImplementedError

    @abstractmethod
    async def wrap_tcp_socket(self, socket: _socket.socket) -> AbstractAsyncStreamSocketAdapter:
        raise NotImplementedError

    @abstractmethod
    async def create_tcp_listeners(
        self,
        host: str | Sequence[str],
        port: int,
        *,
        family: int,
        backlog: int,
        reuse_port: bool,
    ) -> Sequence[AbstractAsyncListenerSocketAdapter]:
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
    def create_lock(self) -> ILock:
        raise NotImplementedError

    async def wait_future(self, future: concurrent.futures.Future[_T]) -> _T:
        while not future.done():
            await self.coro_yield()
        return future.result()
