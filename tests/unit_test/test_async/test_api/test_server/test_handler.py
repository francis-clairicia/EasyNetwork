# mypy: disable_error_code=func-returns-value

from __future__ import annotations

import contextlib
import inspect
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any

from easynetwork.servers.async_tcp import AsyncTCPNetworkServer
from easynetwork.servers.async_udp import AsyncUDPNetworkServer
from easynetwork.servers.handlers import AsyncBaseClientInterface, AsyncDatagramRequestHandler, AsyncStreamRequestHandler

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class BaseFakeHandler:
    __slots__ = ()

    def handle(self, client: AsyncBaseClientInterface[Any]) -> AsyncGenerator[None, Any]:
        raise NotImplementedError


class FakeStreamHandler(BaseFakeHandler, AsyncStreamRequestHandler[Any, Any]):
    __slots__ = ()


class FakeDatagramHandler(BaseFakeHandler, AsyncDatagramRequestHandler[Any, Any]):
    __slots__ = ()


@pytest.mark.asyncio
class TestAsyncDatagramRequestHandler:
    @pytest.fixture
    @staticmethod
    def request_handler() -> AsyncDatagramRequestHandler[Any, Any]:
        return FakeDatagramHandler()

    @pytest.fixture
    @staticmethod
    def mock_server(mocker: MockerFixture) -> MagicMock:
        return mocker.NonCallableMagicMock(spec=AsyncUDPNetworkServer)

    async def test____service_init____return_None(
        self,
        request_handler: AsyncDatagramRequestHandler[Any, Any],
        mock_server: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        assert (await request_handler.service_init(contextlib.AsyncExitStack(), mock_server)) is None


@pytest.mark.asyncio
class TestAsyncStreamRequestHandler:
    @pytest.fixture
    @staticmethod
    def request_handler() -> AsyncStreamRequestHandler[Any, Any]:
        return FakeStreamHandler()

    @pytest.fixture
    @staticmethod
    def mock_server(mocker: MockerFixture) -> MagicMock:
        return mocker.NonCallableMagicMock(spec=AsyncTCPNetworkServer)

    async def test____service_init____return_None(
        self,
        request_handler: AsyncStreamRequestHandler[Any, Any],
        mock_server: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        assert (await request_handler.service_init(contextlib.AsyncExitStack(), mock_server)) is None

    async def test____on_connection____return_None(
        self,
        mock_async_stream_client: MagicMock,
        request_handler: AsyncStreamRequestHandler[Any, Any],
    ) -> None:
        # Arrange

        # Act & Assert
        coro_or_asyncgen = request_handler.on_connection(mock_async_stream_client)
        assert inspect.iscoroutine(coro_or_asyncgen)
        assert (await coro_or_asyncgen) is None

    async def test____on_disconnection____return_None(
        self,
        mock_async_stream_client: MagicMock,
        request_handler: AsyncStreamRequestHandler[Any, Any],
    ) -> None:
        # Arrange

        # Act & Assert
        assert (await request_handler.on_disconnection(mock_async_stream_client)) is None
