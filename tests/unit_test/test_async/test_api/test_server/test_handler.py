# -*- coding: utf-8 -*-
# mypy: disable_error_code=func-returns-value

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any, AsyncGenerator

from easynetwork.api_async.server.handler import AsyncBaseRequestHandler, AsyncClientInterface, AsyncStreamRequestHandler
from easynetwork.exceptions import BaseProtocolParseError
from easynetwork.tools.socket import IPv4SocketAddress

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class FakeClient(AsyncClientInterface[Any]):
    async def send_packet(self, packet: Any) -> None:
        raise NotImplementedError

    def is_closing(self) -> bool:
        raise NotImplementedError

    async def aclose(self) -> None:
        raise NotImplementedError

    @property
    def socket(self) -> Any:
        raise NotImplementedError


class BaseFakeHandler(AsyncBaseRequestHandler[Any, Any]):
    __slots__ = ()

    def handle(self, client: AsyncClientInterface[Any]) -> AsyncGenerator[None, Any]:
        raise NotImplementedError

    async def bad_request(self, client: AsyncClientInterface[str], exc: BaseProtocolParseError, /) -> None:
        pass


class FakeStreamHandler(AsyncStreamRequestHandler[Any, Any], BaseFakeHandler):
    __slots__ = ()


@pytest.mark.asyncio
class TestAsyncClientInterface:
    async def test____address____saved_address_is_good(self) -> None:
        # Arrange
        address = IPv4SocketAddress("127.0.0.1", 12345)

        # Act
        client = FakeClient(address)

        # Assert
        assert client.address is address


@pytest.mark.asyncio
class BaseCommonTestsForRequestHandler:
    async def test____set_async_backend____return_None(
        self,
        mock_backend: MagicMock,
        request_handler: AsyncBaseRequestHandler[Any, Any],
    ) -> None:
        # Arrange

        # Act & Assert
        assert request_handler.set_async_backend(mock_backend) is None

    async def test____service_init____return_None(
        self,
        request_handler: AsyncBaseRequestHandler[Any, Any],
    ) -> None:
        # Arrange

        # Act & Assert
        assert (await request_handler.service_init()) is None

    async def test____service_quit____return_None(
        self,
        request_handler: AsyncBaseRequestHandler[Any, Any],
    ) -> None:
        # Arrange

        # Act & Assert
        assert (await request_handler.service_quit()) is None

    async def test____service_actions____return_None(
        self,
        request_handler: AsyncBaseRequestHandler[Any, Any],
    ) -> None:
        # Arrange

        # Act & Assert
        assert (await request_handler.service_actions()) is None


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
        mock_async_client: MagicMock,
        request_handler: AsyncStreamRequestHandler[Any, Any],
    ) -> None:
        # Arrange

        # Act & Assert
        coro_or_asyncgen = request_handler.on_connection(mock_async_client)
        assert inspect.iscoroutine(coro_or_asyncgen)
        assert (await coro_or_asyncgen) is None

    async def test____on_disconnection____return_None(
        self,
        mock_async_client: MagicMock,
        request_handler: AsyncStreamRequestHandler[Any, Any],
    ) -> None:
        # Arrange

        # Act & Assert
        assert (await request_handler.on_disconnection(mock_async_client)) is None
