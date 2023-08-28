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
"""Asynchronous backend engine interfaces module"""

from __future__ import annotations

__all__ = [
    "AcceptedSocket",
    "AsyncBackend",
    "AsyncBaseSocketAdapter",
    "AsyncDatagramSocketAdapter",
    "AsyncHalfCloseableStreamSocketAdapter",
    "AsyncListenerSocketAdapter",
    "AsyncStreamSocketAdapter",
    "ICondition",
    "IEvent",
    "ILock",
    "Task",
    "TaskGroup",
    "ThreadsPortal",
    "TimeoutHandle",
]

import contextvars
import math
from abc import ABCMeta, abstractmethod
from collections.abc import Callable, Coroutine, Iterable, Sequence
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING, Any, Generic, NoReturn, ParamSpec, Protocol, Self, TypeVar

if TYPE_CHECKING:
    import concurrent.futures
    import socket as _socket
    import ssl as _typing_ssl
    from types import TracebackType

    from ...tools.socket import ISocket


_P = ParamSpec("_P")
_T = TypeVar("_T")
_T_co = TypeVar("_T_co", covariant=True)


class ILock(Protocol):
    async def __aenter__(self) -> Any:  # pragma: no cover
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
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

    def is_set(self) -> bool:  # pragma: no cover
        ...


class ICondition(ILock, Protocol):
    def notify(self, n: int = ..., /) -> None:  # pragma: no cover
        ...

    def notify_all(self) -> None:  # pragma: no cover
        ...

    async def wait(self) -> Any:  # pragma: no cover
        ...


class Runner(metaclass=ABCMeta):
    __slots__ = ("__weakref__",)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None) -> None:
        self.close()

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def run(self, coro_func: Callable[..., Coroutine[Any, Any, _T]], *args: Any) -> _T:
        raise NotImplementedError


class Task(Generic[_T_co], metaclass=ABCMeta):
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


class SystemTask(Task[_T_co]):
    __slots__ = ()

    @abstractmethod
    async def join_or_cancel(self) -> _T_co:
        raise NotImplementedError


class TaskGroup(metaclass=ABCMeta):
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
        coro_func: Callable[_P, Coroutine[Any, Any, _T]],
        /,
        *args: _P.args,
        **kwargs: _P.kwargs,
    ) -> Task[_T]:
        raise NotImplementedError

    def start_soon_with_context(
        self,
        context: contextvars.Context,
        coro_func: Callable[_P, Coroutine[Any, Any, _T]],
        /,
        *args: _P.args,
        **kwargs: _P.kwargs,
    ) -> Task[_T]:
        raise NotImplementedError("contextvars.Context management not supported by this backend")


class ThreadsPortal(metaclass=ABCMeta):
    __slots__ = ("__weakref__",)

    @abstractmethod
    def run_coroutine(self, coro_func: Callable[_P, Coroutine[Any, Any, _T]], /, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        raise NotImplementedError

    @abstractmethod
    def run_sync(self, func: Callable[_P, _T], /, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        raise NotImplementedError


class AsyncBaseSocketAdapter(metaclass=ABCMeta):
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


class AsyncStreamSocketAdapter(AsyncBaseSocketAdapter):
    __slots__ = ()

    @abstractmethod
    def get_remote_address(self) -> tuple[Any, ...]:
        raise NotImplementedError

    @abstractmethod
    async def recv(self, bufsize: int, /) -> bytes:
        raise NotImplementedError

    @abstractmethod
    async def sendall(self, data: bytes, /) -> None:
        raise NotImplementedError

    async def sendall_fromiter(self, iterable_of_data: Iterable[bytes], /) -> None:
        await self.sendall(b"".join(iterable_of_data))


class AsyncHalfCloseableStreamSocketAdapter(AsyncStreamSocketAdapter):
    __slots__ = ()

    @abstractmethod
    async def send_eof(self) -> None:
        raise NotImplementedError


class AsyncDatagramSocketAdapter(AsyncBaseSocketAdapter):
    __slots__ = ()

    @abstractmethod
    def get_remote_address(self) -> tuple[Any, ...] | None:
        raise NotImplementedError

    @abstractmethod
    async def recvfrom(self, bufsize: int, /) -> tuple[bytes, tuple[Any, ...]]:
        raise NotImplementedError

    @abstractmethod
    async def sendto(self, data: bytes, address: tuple[Any, ...] | None, /) -> None:
        raise NotImplementedError


class AsyncListenerSocketAdapter(AsyncBaseSocketAdapter):
    __slots__ = ()

    @abstractmethod
    async def accept(self) -> AcceptedSocket:
        raise NotImplementedError


class AcceptedSocket(metaclass=ABCMeta):
    __slots__ = ()

    @abstractmethod
    async def connect(self) -> AsyncStreamSocketAdapter:
        raise NotImplementedError


class TimeoutHandle(metaclass=ABCMeta):
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
        self.reschedule(math.inf)


class AsyncBackend(metaclass=ABCMeta):
    __slots__ = ("__weakref__",)

    @abstractmethod
    def new_runner(self) -> Runner:
        raise NotImplementedError

    def bootstrap(self, coro_func: Callable[..., Coroutine[Any, Any, _T]], *args: Any) -> _T:
        with self.new_runner() as runner:
            return runner.run(coro_func, *args)

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
    def timeout(self, delay: float) -> AbstractAsyncContextManager[TimeoutHandle]:
        raise NotImplementedError

    @abstractmethod
    def timeout_at(self, deadline: float) -> AbstractAsyncContextManager[TimeoutHandle]:
        raise NotImplementedError

    @abstractmethod
    def move_on_after(self, delay: float) -> AbstractAsyncContextManager[TimeoutHandle]:
        raise NotImplementedError

    @abstractmethod
    def move_on_at(self, deadline: float) -> AbstractAsyncContextManager[TimeoutHandle]:
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
    def spawn_task(
        self,
        coro_func: Callable[_P, Coroutine[Any, Any, _T]],
        /,
        *args: _P.args,
        **kwargs: _P.kwargs,
    ) -> SystemTask[_T]:
        raise NotImplementedError

    @abstractmethod
    def create_task_group(self) -> TaskGroup:
        raise NotImplementedError

    @abstractmethod
    async def create_tcp_connection(
        self,
        host: str,
        port: int,
        *,
        local_address: tuple[str, int] | None = ...,
        happy_eyeballs_delay: float | None = ...,
    ) -> AsyncStreamSocketAdapter:
        raise NotImplementedError

    async def create_ssl_over_tcp_connection(
        self,
        host: str,
        port: int,
        ssl_context: _typing_ssl.SSLContext,
        *,
        server_hostname: str | None,
        ssl_handshake_timeout: float,
        ssl_shutdown_timeout: float,
        local_address: tuple[str, int] | None = ...,
        happy_eyeballs_delay: float | None = ...,
    ) -> AsyncStreamSocketAdapter:
        raise NotImplementedError("SSL/TLS is not supported by this backend")

    @abstractmethod
    async def wrap_tcp_client_socket(self, socket: _socket.socket) -> AsyncStreamSocketAdapter:
        raise NotImplementedError

    async def wrap_ssl_over_tcp_client_socket(
        self,
        socket: _socket.socket,
        ssl_context: _typing_ssl.SSLContext,
        *,
        server_hostname: str,
        ssl_handshake_timeout: float,
        ssl_shutdown_timeout: float,
    ) -> AsyncStreamSocketAdapter:
        raise NotImplementedError("SSL/TLS is not supported by this backend")

    @abstractmethod
    async def create_tcp_listeners(
        self,
        host: str | Sequence[str] | None,
        port: int,
        backlog: int,
        *,
        reuse_port: bool = ...,
    ) -> Sequence[AsyncListenerSocketAdapter]:
        raise NotImplementedError

    async def create_ssl_over_tcp_listeners(
        self,
        host: str | Sequence[str] | None,
        port: int,
        backlog: int,
        ssl_context: _typing_ssl.SSLContext,
        *,
        ssl_handshake_timeout: float,
        ssl_shutdown_timeout: float,
        reuse_port: bool = ...,
    ) -> Sequence[AsyncListenerSocketAdapter]:
        raise NotImplementedError("SSL/TLS is not supported by this backend")

    @abstractmethod
    async def create_udp_endpoint(
        self,
        *,
        local_address: tuple[str, int] | None = ...,
        remote_address: tuple[str, int] | None = ...,
        reuse_port: bool = ...,
    ) -> AsyncDatagramSocketAdapter:
        raise NotImplementedError

    @abstractmethod
    async def wrap_udp_socket(self, socket: _socket.socket) -> AsyncDatagramSocketAdapter:
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
    async def run_in_thread(self, func: Callable[_P, _T], /, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        raise NotImplementedError

    @abstractmethod
    def create_threads_portal(self) -> ThreadsPortal:
        raise NotImplementedError

    @abstractmethod
    async def wait_future(self, future: concurrent.futures.Future[_T_co]) -> _T_co:
        raise NotImplementedError
