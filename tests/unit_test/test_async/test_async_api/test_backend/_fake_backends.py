# -*- coding: Utf-8 -*-

from __future__ import annotations

from socket import socket as Socket
from typing import Any, final

from easynetwork.async_api.backend.abc import (
    AbstractAsyncBackend,
    AbstractDatagramSocketAdapter,
    AbstractStreamSocketAdapter,
    ILock,
)


class BaseFakeBackend(AbstractAsyncBackend):
    async def coro_yield(self) -> None:
        raise NotImplementedError

    async def create_tcp_connection(self, *args: Any, **kwargs: Any) -> AbstractStreamSocketAdapter:
        raise NotImplementedError

    async def wrap_tcp_socket(self, socket: Socket) -> AbstractStreamSocketAdapter:
        raise NotImplementedError

    async def create_udp_endpoint(self, *args: Any, **kwargs: Any) -> AbstractDatagramSocketAdapter:
        raise NotImplementedError

    async def wrap_udp_socket(self, socket: Socket) -> AbstractDatagramSocketAdapter:
        raise NotImplementedError

    def create_lock(self) -> ILock:
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
