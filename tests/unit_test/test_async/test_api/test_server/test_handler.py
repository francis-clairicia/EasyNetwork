# -*- coding: Utf-8 -*-
# mypy: disable_error_code=func-returns-value

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from easynetwork.api_async.server.handler import (
    AsyncBaseRequestHandler,
    AsyncClientInterface,
    AsyncDatagramRequestHandler,
    AsyncStreamRequestHandler,
)
from easynetwork.exceptions import BaseProtocolParseError
from easynetwork.tools.socket import IPv4SocketAddress

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock


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

    async def handle(self, request: Any, client: AsyncClientInterface[Any]) -> None:
        raise NotImplementedError


class FakeStreamHandler(AsyncStreamRequestHandler[Any, Any], BaseFakeHandler):
    __slots__ = ()


class FakeDatagramHandler(AsyncDatagramRequestHandler[Any, Any], BaseFakeHandler):
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
    async def test____service_init____return_None(
        self,
        mock_backend: MagicMock,
        request_handler: AsyncBaseRequestHandler[Any, Any],
    ) -> None:
        # Arrange

        # Act & Assert
        assert (await request_handler.service_init(mock_backend)) is None

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

    async def test____bad_request____return_None(
        self,
        mock_async_client: MagicMock,
        request_handler: AsyncBaseRequestHandler[Any, Any],
    ) -> None:
        # Arrange

        # Act & Assert
        assert (await request_handler.bad_request(mock_async_client, BaseProtocolParseError("deserialization", "test"))) is None

    async def test____handle_error____return_False(
        self,
        mock_async_client: MagicMock,
        request_handler: AsyncBaseRequestHandler[Any, Any],
    ) -> None:
        # Arrange

        # Act & Assert
        assert (await request_handler.handle_error(mock_async_client, BaseProtocolParseError("deserialization", "test"))) is False


class TestAsyncStreamRequestHandler(BaseCommonTestsForRequestHandler):
    @pytest.fixture
    @staticmethod
    def request_handler() -> AsyncStreamRequestHandler[Any, Any]:
        return FakeStreamHandler()

    async def test____on_connection____return_None(
        self,
        mock_async_client: MagicMock,
        request_handler: AsyncStreamRequestHandler[Any, Any],
    ) -> None:
        # Arrange

        # Act & Assert
        assert (await request_handler.on_connection(mock_async_client)) is None

    async def test____on_disconnection____return_None(
        self,
        mock_async_client: MagicMock,
        request_handler: AsyncStreamRequestHandler[Any, Any],
    ) -> None:
        # Arrange

        # Act & Assert
        assert (await request_handler.on_disconnection(mock_async_client)) is None


class TestAsyncDatagramRequestHandler(BaseCommonTestsForRequestHandler):
    @pytest.fixture
    @staticmethod
    def request_handler() -> AsyncDatagramRequestHandler[Any, Any]:
        return FakeDatagramHandler()

    async def test____accept_request_from____return_True(
        self,
        request_handler: AsyncDatagramRequestHandler[Any, Any],
    ) -> None:
        # Arrange

        # Act & Assert
        assert (await request_handler.accept_request_from(IPv4SocketAddress("127.0.0.1", 12345))) is True
