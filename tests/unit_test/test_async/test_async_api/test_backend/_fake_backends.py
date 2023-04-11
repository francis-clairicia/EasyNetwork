# -*- coding: Utf-8 -*-

from __future__ import annotations

from socket import socket as Socket
from typing import Any, Callable, Coroutine, Sequence, final

from easynetwork.api_async.backend.abc import (
    AbstractAsyncBackend,
    AbstractAsyncDatagramSocketAdapter,
    AbstractAsyncListenerSocketAdapter,
    AbstractAsyncStreamSocketAdapter,
    AbstractTaskGroup,
    IEvent,
    ILock,
)


class BaseFakeBackend(AbstractAsyncBackend):
    async def sleep(self, delay: float) -> None:
        raise NotImplementedError

    def current_time(self) -> float:
        raise NotImplementedError

    async def coro_yield(self) -> None:
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

    def run_coroutine_from_thread(self, __func: Callable[..., Coroutine[Any, Any, Any]], /, *args: Any, **kwargs: Any) -> Any:
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
