from __future__ import annotations

import contextlib
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any

from easynetwork.servers.handlers import (
    AsyncDatagramClient,
    AsyncDatagramRequestHandler,
    AsyncStreamClient,
    AsyncStreamRequestHandler,
)
from easynetwork.servers.misc import build_lowlevel_datagram_server_handler, build_lowlevel_stream_server_handler

import pytest

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


class _DummyStreamRequestHandler(AsyncStreamRequestHandler[Any, Any]):
    def __init__(self, max_nb_yields: int) -> None:
        self.max_nb_yields: int = max_nb_yields

    async def handle(self, client: AsyncStreamClient[Any]) -> AsyncGenerator[float, Any]:
        for _ in range(self.max_nb_yields):
            data = yield 1234567.89
            await client.send_packet(data)


class _DummyDatagramRequestHandler(AsyncDatagramRequestHandler[Any, Any]):
    def __init__(self, max_nb_yields: int) -> None:
        self.max_nb_yields: int = max_nb_yields

    async def handle(self, client: AsyncDatagramClient[Any]) -> AsyncGenerator[float, Any]:
        for _ in range(self.max_nb_yields):
            data = yield 1234567.89
            await client.send_packet(data)


@pytest.mark.asyncio
async def test____build_lowlevel_datagram_server_handler____skip_initialization(mocker: MockerFixture) -> None:
    # Arrange

    @contextlib.asynccontextmanager
    async def initializer(client: Any) -> AsyncGenerator[None]:
        yield

    ctx = mocker.sentinel.ctx
    handler = build_lowlevel_datagram_server_handler(initializer, _DummyDatagramRequestHandler(0))

    # Act
    generator = handler(ctx)
    with pytest.raises(StopAsyncIteration):
        await anext(generator)


@pytest.mark.asyncio
async def test____build_lowlevel_stream_server_handler____skip_initialization(mocker: MockerFixture) -> None:
    # Arrange

    @contextlib.asynccontextmanager
    async def initializer(client: Any) -> AsyncGenerator[None]:
        yield

    ctx = mocker.sentinel.ctx
    handler = build_lowlevel_stream_server_handler(initializer, _DummyStreamRequestHandler(0))

    # Act
    generator = handler(ctx)
    with pytest.raises(StopAsyncIteration):
        await anext(generator)
