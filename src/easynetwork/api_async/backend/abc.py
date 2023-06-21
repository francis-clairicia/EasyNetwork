# -*- coding: utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""
Asynchronous client/server module
"""

from __future__ import annotations

__all__ = [
    "AbstractAcceptedSocket",
    "AbstractAsyncBackend",
    "AbstractAsyncBaseSocketAdapter",
    "AbstractAsyncDatagramSocketAdapter",
    "AbstractAsyncListenerSocketAdapter",
    "AbstractAsyncStreamSocketAdapter",
    "AbstractTask",
    "AbstractTaskGroup",
    "AbstractThreadsPortal",
    "AbstractTimeoutHandle",
    "ICondition",
    "IEvent",
    "ILock",
]

from abc import ABCMeta, abstractmethod
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncContextManager,
    Callable,
    Coroutine,
    Generic,
    NoReturn,
    ParamSpec,
    Protocol,
    Self,
    Sequence,
    TypeVar,
)

if TYPE_CHECKING:
    import concurrent.futures
    import socket as _socket
    import ssl as _ssl
    from types import TracebackType

    from _typeshed import ReadableBuffer

    from ...tools.socket import ISocket


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


class IEvent(Protocol):
    async def wait(self) -> Any:  # pragma: no cover
        ...

    def set(self) -> None:  # pragma: no cover
        ...

    def clear(self) -> None:  # pragma: no cover
        ...

    def is_set(self) -> bool:  # pragma: no cover
        ...


class ICondition(ILock, Protocol):
    def notify(self, __n: int = ..., /) -> None:  # pragma: no cover
        ...

    def notify_all(self) -> None:  # pragma: no cover
        ...

    async def wait(self) -> Any:  # pragma: no cover
        ...


class AbstractTask(Generic[_T_co], metaclass=ABCMeta):
    __slots__ = ("__weakref__",)

    @abstractmethod
    def done(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def cancel(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def cancelled(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def wait(self) -> None:
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
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def start_soon(
        self,
        __coro_func: Callable[_P, Coroutine[Any, Any, _T]],
        /,
        *args: _P.args,
        **kwargs: _P.kwargs,
    ) -> AbstractTask[_T]:
        raise NotImplementedError


class AbstractThreadsPortal(metaclass=ABCMeta):
    __slots__ = ("__weakref__",)

    @abstractmethod
    def run_coroutine(self, __coro_func: Callable[_P, Coroutine[Any, Any, _T]], /, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        raise NotImplementedError

    @abstractmethod
    def run_sync(self, __func: Callable[_P, _T], /, *args: _P.args, **kwargs: _P.kwargs) -> _T:
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
        await self.aclose()

    @abstractmethod
    def is_closing(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def aclose(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_local_address(self) -> tuple[Any, ...]:
        raise NotImplementedError

    @abstractmethod
    def socket(self) -> ISocket:
        raise NotImplementedError


class AbstractAsyncStreamSocketAdapter(AbstractAsyncBaseSocketAdapter):
    __slots__ = ()

    @abstractmethod
    def get_remote_address(self) -> tuple[Any, ...]:
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
    def get_remote_address(self) -> tuple[Any, ...] | None:
        raise NotImplementedError

    @abstractmethod
    async def recvfrom(self) -> tuple[bytes, tuple[Any, ...]]:
        raise NotImplementedError

    @abstractmethod
    async def sendto(self, __data: ReadableBuffer, __address: tuple[Any, ...] | None, /) -> None:
        raise NotImplementedError


class AbstractAsyncListenerSocketAdapter(AbstractAsyncBaseSocketAdapter):
    __slots__ = ()

    @abstractmethod
    async def accept(self) -> AbstractAcceptedSocket:
        raise NotImplementedError


class AbstractAcceptedSocket(metaclass=ABCMeta):
    __slots__ = ()

    @abstractmethod
    async def connect(self) -> AbstractAsyncStreamSocketAdapter:
        raise NotImplementedError


class AbstractTimeoutHandle(metaclass=ABCMeta):
    __slots__ = ()

    @abstractmethod
    def when(self) -> float:
        raise NotImplementedError

    @abstractmethod
    def reschedule(self, when: float) -> None:
        raise NotImplementedError

    @abstractmethod
    def expired(self) -> bool:
        raise NotImplementedError

    @property
    def deadline(self) -> float:
        return self.when()

    @deadline.setter
    def deadline(self, value: float) -> None:
        self.reschedule(value)

    @deadline.deleter
    def deadline(self) -> None:
        self.reschedule(float("+inf"))


class AbstractAsyncBackend(metaclass=ABCMeta):
    __slots__ = ("__weakref__",)

    @abstractmethod
    def bootstrap(self, coro_func: Callable[..., Coroutine[Any, Any, _T]], *args: Any) -> _T:
        raise NotImplementedError

    @abstractmethod
    async def coro_yield(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def cancel_shielded_coro_yield(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_cancelled_exc_class(self) -> type[BaseException]:
        raise NotImplementedError

    @abstractmethod
    async def ignore_cancellation(self, coroutine: Coroutine[Any, Any, _T_co]) -> _T_co:
        raise NotImplementedError

    @abstractmethod
    def timeout(self, delay: float) -> AsyncContextManager[AbstractTimeoutHandle]:
        raise NotImplementedError

    @abstractmethod
    def timeout_at(self, deadline: float) -> AsyncContextManager[AbstractTimeoutHandle]:
        raise NotImplementedError

    @abstractmethod
    def current_time(self) -> float:
        raise NotImplementedError

    @abstractmethod
    async def sleep(self, delay: float) -> None:
        raise NotImplementedError

    @abstractmethod
    async def sleep_forever(self) -> NoReturn:
        raise NotImplementedError

    async def sleep_until(self, deadline: float) -> None:
        return await self.sleep(max(deadline - self.current_time(), 0))

    @abstractmethod
    def create_task_group(self) -> AbstractTaskGroup:
        raise NotImplementedError

    @abstractmethod
    async def create_tcp_connection(
        self,
        host: str,
        port: int,
        *,
        local_address: tuple[str, int] | None = ...,
        happy_eyeballs_delay: float | None = ...,
    ) -> AbstractAsyncStreamSocketAdapter:
        raise NotImplementedError

    async def create_ssl_over_tcp_connection(
        self,
        host: str,
        port: int,
        ssl_context: _ssl.SSLContext,
        *,
        server_hostname: str | None,
        ssl_handshake_timeout: float,
        ssl_shutdown_timeout: float,
        local_address: tuple[str, int] | None = ...,
        happy_eyeballs_delay: float | None = ...,
    ) -> AbstractAsyncStreamSocketAdapter:
        raise NotImplementedError("SSL/TLS is not supported by this backend")

    @abstractmethod
    async def wrap_tcp_client_socket(self, socket: _socket.socket) -> AbstractAsyncStreamSocketAdapter:
        raise NotImplementedError

    async def wrap_ssl_over_tcp_client_socket(
        self,
        socket: _socket.socket,
        ssl_context: _ssl.SSLContext,
        *,
        server_hostname: str,
        ssl_handshake_timeout: float,
        ssl_shutdown_timeout: float,
    ) -> AbstractAsyncStreamSocketAdapter:
        raise NotImplementedError("SSL/TLS is not supported by this backend")

    @abstractmethod
    async def create_tcp_listeners(
        self,
        host: str | Sequence[str] | None,
        port: int,
        backlog: int,
        *,
        reuse_port: bool = ...,
    ) -> Sequence[AbstractAsyncListenerSocketAdapter]:
        raise NotImplementedError

    async def create_ssl_over_tcp_listeners(
        self,
        host: str | Sequence[str] | None,
        port: int,
        backlog: int,
        ssl_context: _ssl.SSLContext,
        *,
        ssl_handshake_timeout: float,
        ssl_shutdown_timeout: float,
        reuse_port: bool = ...,
    ) -> Sequence[AbstractAsyncListenerSocketAdapter]:
        raise NotImplementedError("SSL/TLS is not supported by this backend")

    @abstractmethod
    async def create_udp_endpoint(
        self,
        *,
        local_address: tuple[str | None, int] | None = ...,
        remote_address: tuple[str, int] | None = ...,
        reuse_port: bool = ...,
    ) -> AbstractAsyncDatagramSocketAdapter:
        raise NotImplementedError

    @abstractmethod
    async def wrap_udp_socket(self, socket: _socket.socket) -> AbstractAsyncDatagramSocketAdapter:
        raise NotImplementedError

    @abstractmethod
    def create_lock(self) -> ILock:
        raise NotImplementedError

    @abstractmethod
    def create_event(self) -> IEvent:
        raise NotImplementedError

    @abstractmethod
    def create_condition_var(self, lock: ILock | None = ...) -> ICondition:
        raise NotImplementedError

    @abstractmethod
    async def run_in_thread(self, __func: Callable[_P, _T], /, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        raise NotImplementedError

    @abstractmethod
    def create_threads_portal(self) -> AbstractThreadsPortal:
        raise NotImplementedError

    @abstractmethod
    async def wait_future(self, future: concurrent.futures.Future[_T_co]) -> _T_co:
        raise NotImplementedError
