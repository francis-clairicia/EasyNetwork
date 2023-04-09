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
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Coroutine, Generic, ParamSpec, Protocol, Self, Sequence, TypeVar

if TYPE_CHECKING:
    import concurrent.futures
    import socket as _socket
    from types import TracebackType

    from _typeshed import ReadableBuffer

    from ...tools.socket import ISocket


_P = ParamSpec("_P")
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
    def start_soon(
        self,
        __coro_func: Callable[_P, Coroutine[Any, Any, _T_co]],
        /,
        *args: _P.args,
        **kwargs: _P.kwargs,
    ) -> AbstractTask[_T_co]:
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
        host: str | Sequence[str] | None,
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
        local_address: tuple[str | None, int] | None,
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
    async def run_in_thread(self, __func: Callable[_P, _T_co], /, *args: _P.args, **kwargs: _P.kwargs) -> _T_co:
        raise NotImplementedError

    @abstractmethod
    def run_coroutine_from_thread(
        self,
        __coro_func: Callable[_P, Coroutine[Any, Any, _T_co]],
        /,
        *args: _P.args,
        **kwargs: _P.kwargs,
    ) -> _T_co:
        raise NotImplementedError

    def run_sync_threadsafe(self, __func: Callable[_P, _T_co], /, *args: _P.args, **kwargs: _P.kwargs) -> _T_co:
        async def _func_as_coroutine() -> _T_co:
            return __func(*args, **kwargs)

        return self.run_coroutine_from_thread(_func_as_coroutine)

    async def wait_future(self, future: concurrent.futures.Future[_T_co]) -> _T_co:
        while not future.done():
            await self.coro_yield()
        return future.result()

    async def run_task_once(
        self,
        coroutine_cb: Callable[[], Awaitable[_T_co]],
        task_future: concurrent.futures.Future[_T_co],
    ) -> _T_co:
        if task_future.done() or task_future.running():
            # Use wait_future() because concurrent.futures.CancelledError can be translated to an other exception
            # meaningful for the runner implementation
            del coroutine_cb
            return await self.wait_future(task_future)
        running = task_future.set_running_or_notify_cancel()
        assert running, "Unexpected future cancellation"
        try:
            result: _T_co = await coroutine_cb()
        except BaseException as exc:
            task_future.set_exception(exc)
            raise
        else:
            task_future.set_result(result)
            return result
        finally:
            del task_future, coroutine_cb
