# -*- coding: Utf-8 -*-

from __future__ import annotations

from socket import socket as Socket
from typing import Any, final

from easynetwork.api_async.backend.abc import (
    AbstractAsyncBackend,
    AbstractAsyncDatagramServerAdapter,
    AbstractAsyncDatagramSocketAdapter,
    AbstractAsyncServerAdapter,
    AbstractAsyncStreamSocketAdapter,
    ILock,
)


class BaseFakeBackend(AbstractAsyncBackend):
    async def coro_yield(self) -> None:
        raise NotImplementedError

    async def create_tcp_connection(self, *args: Any, **kwargs: Any) -> AbstractAsyncStreamSocketAdapter:
        raise NotImplementedError

    async def wrap_tcp_socket(self, socket: Socket) -> AbstractAsyncStreamSocketAdapter:
        raise NotImplementedError

    async def create_tcp_server(self, *args: Any, **kwargs: Any) -> AbstractAsyncServerAdapter:
        raise NotImplementedError

    async def create_udp_endpoint(self, *args: Any, **kwargs: Any) -> AbstractAsyncDatagramSocketAdapter:
        raise NotImplementedError

    async def wrap_udp_socket(self, socket: Socket) -> AbstractAsyncDatagramSocketAdapter:
        raise NotImplementedError

    async def create_udp_server(self, *args: Any, **kwargs: Any) -> AbstractAsyncDatagramServerAdapter:
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
