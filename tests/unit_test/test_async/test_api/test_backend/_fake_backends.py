# -*- coding: Utf-8 -*-

from __future__ import annotations

from socket import socket as Socket
from typing import Any, Callable, Coroutine, NoReturn, Sequence, final

from easynetwork.api_async.backend.abc import (
    AbstractAsyncBackend,
    AbstractAsyncDatagramSocketAdapter,
    AbstractAsyncListenerSocketAdapter,
    AbstractAsyncStreamSocketAdapter,
    AbstractAsyncThreadPoolExecutor,
    AbstractTaskGroup,
    AbstractThreadsPortal,
    IEvent,
    ILock,
)


class BaseFakeBackend(AbstractAsyncBackend):
    async def sleep(self, delay: float) -> None:
        raise NotImplementedError

    async def sleep_forever(self) -> NoReturn:
        raise NotImplementedError

    def current_time(self) -> float:
        raise NotImplementedError

    async def coro_yield(self) -> None:
        raise NotImplementedError

    async def ignore_cancellation(self, coroutine: Coroutine[Any, Any, Any]) -> Any:
        raise NotImplementedError

    def get_cancelled_exc_class(self) -> type[BaseException]:
        raise NotImplementedError

    def create_task_group(self) -> AbstractTaskGroup:
        raise NotImplementedError

    async def create_tcp_connection(self, *args: Any, **kwargs: Any) -> AbstractAsyncStreamSocketAdapter:
        raise NotImplementedError

    async def wrap_tcp_client_socket(self, socket: Socket) -> AbstractAsyncStreamSocketAdapter:
        raise NotImplementedError

    async def create_tcp_listeners(self, *args: Any, **kwargs: Any) -> Sequence[AbstractAsyncListenerSocketAdapter]:
        raise NotImplementedError

    async def create_udp_endpoint(self, *args: Any, **kwargs: Any) -> AbstractAsyncDatagramSocketAdapter:
        raise NotImplementedError

    async def wrap_udp_socket(self, socket: Socket) -> AbstractAsyncDatagramSocketAdapter:
        raise NotImplementedError

    def create_lock(self) -> ILock:
        raise NotImplementedError

    def create_event(self) -> IEvent:
        raise NotImplementedError

    async def run_in_thread(self, __func: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    def create_thread_pool_executor(self, *args: Any, **kwargs: Any) -> AbstractAsyncThreadPoolExecutor:
        raise NotImplementedError

    def create_threads_portal(self) -> AbstractThreadsPortal:
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
