from __future__ import annotations

from collections.abc import Callable, Coroutine, Sequence
from socket import socket as Socket
from typing import Any, AsyncContextManager, NoReturn, final

from easynetwork.api_async.backend.abc import (
    AsyncBackend,
    AsyncDatagramSocketAdapter,
    AsyncListenerSocketAdapter,
    AsyncStreamSocketAdapter,
    ICondition,
    IEvent,
    ILock,
    Runner,
    SystemTask,
    TaskGroup,
    ThreadsPortal,
    TimeoutHandle,
)


class BaseFakeBackend(AsyncBackend):
    def new_runner(self) -> Runner:
        raise NotImplementedError

    async def sleep(self, delay: float) -> None:
        raise NotImplementedError

    async def sleep_forever(self) -> NoReturn:
        raise NotImplementedError

    def current_time(self) -> float:
        raise NotImplementedError

    async def coro_yield(self) -> None:
        raise NotImplementedError

    async def cancel_shielded_coro_yield(self) -> None:
        raise NotImplementedError

    async def ignore_cancellation(self, coroutine: Coroutine[Any, Any, Any]) -> Any:
        raise NotImplementedError

    def timeout(self, delay: Any) -> AsyncContextManager[TimeoutHandle]:
        raise NotImplementedError

    def timeout_at(self, deadline: Any) -> AsyncContextManager[TimeoutHandle]:
        raise NotImplementedError

    def move_on_after(self, delay: Any) -> AsyncContextManager[TimeoutHandle]:
        raise NotImplementedError

    def move_on_at(self, deadline: Any) -> AsyncContextManager[TimeoutHandle]:
        raise NotImplementedError

    def get_cancelled_exc_class(self) -> type[BaseException]:
        raise NotImplementedError

    def spawn_task(self, *args: Any, **kwargs: Any) -> SystemTask[Any]:
        raise NotImplementedError

    def create_task_group(self) -> TaskGroup:
        raise NotImplementedError

    async def create_tcp_connection(self, *args: Any, **kwargs: Any) -> AsyncStreamSocketAdapter:
        raise NotImplementedError

    async def wrap_tcp_client_socket(self, socket: Socket) -> AsyncStreamSocketAdapter:
        raise NotImplementedError

    async def create_tcp_listeners(self, *args: Any, **kwargs: Any) -> Sequence[AsyncListenerSocketAdapter]:
        raise NotImplementedError

    async def create_udp_endpoint(self, *args: Any, **kwargs: Any) -> AsyncDatagramSocketAdapter:
        raise NotImplementedError

    async def wrap_udp_socket(self, socket: Socket) -> AsyncDatagramSocketAdapter:
        raise NotImplementedError

    def create_lock(self) -> ILock:
        raise NotImplementedError

    def create_event(self) -> IEvent:
        raise NotImplementedError

    def create_condition_var(self, lock: ILock | None = ...) -> ICondition:
        raise NotImplementedError

    async def run_in_thread(self, func: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    def create_threads_portal(self) -> ThreadsPortal:
        raise NotImplementedError

    async def wait_future(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError


@final
class FakeAsyncioBackend(BaseFakeBackend):
    pass


@final
class FakeTrioBackend(BaseFakeBackend):
    pass


@final
class FakeCurioBackend(BaseFakeBackend):
    pass
