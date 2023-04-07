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
    "AbstractTask",
    "AbstractTaskGroup",
    "ILock",
]

from abc import ABCMeta, abstractmethod
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Generic, ParamSpec, Protocol, Self, Sequence, TypeVar

if TYPE_CHECKING:
    import concurrent.futures
    import socket as _socket
    from types import TracebackType

    from _typeshed import ReadableBuffer

    from ...tools.socket import SocketProxy


_P = ParamSpec("_P")
_T = TypeVar("_T")
_T_co = TypeVar("_T_co", covariant=True)


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


class AbstractTask(Generic[_T_co], metaclass=ABCMeta):
    __slots__ = ("__weakref__",)

    @abstractmethod
    def done(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def cancel(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def cancelled(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def join(self) -> _T_co:
        raise NotImplementedError


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
    def start(self, func: Callable[..., Coroutine[Any, Any, _T]], *args: Any) -> AbstractTask[_T]:
        raise NotImplementedError


class AbstractAsyncBaseSocketAdapter(metaclass=ABCMeta):
    __slots__ = ("__weakref__",)

    async def __aenter__(self) -> Self:
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
    def proxy(self) -> SocketProxy:
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
    def getpeername(self) -> tuple[Any, ...] | None:
        raise NotImplementedError

    @abstractmethod
    async def recvfrom(self) -> tuple[bytes, tuple[Any, ...]]:
        raise NotImplementedError

    @abstractmethod
    async def sendto(self, __data: ReadableBuffer, __address: tuple[Any, ...] | None = ..., /) -> None:
        raise NotImplementedError


class AbstractAsyncListenerSocketAdapter(AbstractAsyncBaseSocketAdapter):
    __slots__ = ()

    @abstractmethod
    async def accept(self) -> tuple[AbstractAsyncStreamSocketAdapter, tuple[Any, ...]]:
        raise NotImplementedError


class AbstractAsyncBackend(metaclass=ABCMeta):
    __slots__ = ("__weakref__",)

    @abstractmethod
    async def coro_yield(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def sleep(self, delay: float) -> None:
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
    async def wrap_connected_tcp_socket(self, socket: _socket.socket) -> AbstractAsyncStreamSocketAdapter:
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

    @abstractmethod
    async def run_in_thread(self, __func: Callable[_P, _T], /, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        raise NotImplementedError

    async def wait_future(self, future: concurrent.futures.Future[_T]) -> _T:
        while not future.done():
            await self.coro_yield()
        return future.result()
