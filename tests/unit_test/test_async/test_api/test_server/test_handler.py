# mypy: disable_error_code=func-returns-value

from __future__ import annotations

import inspect
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any

from easynetwork.api_async.server.handler import (
    AsyncBaseClientInterface,
    AsyncBaseRequestHandler,
    AsyncDatagramRequestHandler,
    AsyncStreamRequestHandler,
)
from easynetwork.exceptions import BaseProtocolParseError

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class BaseFakeHandler(AsyncBaseRequestHandler):
    __slots__ = ()

    def handle(self, client: AsyncBaseClientInterface[Any]) -> AsyncGenerator[None, Any]:
        raise NotImplementedError

    async def bad_request(self, client: AsyncBaseClientInterface[Any], exc: BaseProtocolParseError, /) -> None:
        pass


class FakeStreamHandler(BaseFakeHandler, AsyncStreamRequestHandler[Any, Any]):
    __slots__ = ()


class FakeDatagramHandler(BaseFakeHandler, AsyncDatagramRequestHandler[Any, Any]):
    __slots__ = ()


@pytest.mark.asyncio
class BaseCommonTestsForRequestHandler:
    async def test____set_async_backend____return_None(
        self,
        mock_backend: MagicMock,
        request_handler: AsyncBaseRequestHandler,
    ) -> None:
        # Arrange

        # Act & Assert
        assert request_handler.set_async_backend(mock_backend) is None

    async def test____service_init____return_None(
        self,
        request_handler: AsyncBaseRequestHandler,
    ) -> None:
        # Arrange

        # Act & Assert
        assert (await request_handler.service_init()) is None

    async def test____service_quit____return_None(
        self,
        request_handler: AsyncBaseRequestHandler,
    ) -> None:
        # Arrange

        # Act & Assert
        assert (await request_handler.service_quit()) is None

    async def test____service_actions____return_None(
        self,
        request_handler: AsyncBaseRequestHandler,
    ) -> None:
        # Arrange

        # Act & Assert
        assert (await request_handler.service_actions()) is None


class TestAsyncDatagramRequestHandler(BaseCommonTestsForRequestHandler):
    @pytest.fixture
    @staticmethod
    def request_handler() -> AsyncDatagramRequestHandler[Any, Any]:
        return FakeDatagramHandler()


class TestAsyncStreamRequestHandler(BaseCommonTestsForRequestHandler):
    @pytest.fixture
    @staticmethod
    def request_handler() -> AsyncStreamRequestHandler[Any, Any]:
        return FakeStreamHandler()

    async def test____set_stop_listening_callback____return_None(
        self,
        request_handler: AsyncStreamRequestHandler[Any, Any],
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act & Assert
        assert request_handler.set_stop_listening_callback(mocker.stub()) is None

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
