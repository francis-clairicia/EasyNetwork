# mypy: disable_error_code=func-returns-value

from __future__ import annotations

import contextlib
from collections.abc import Generator
from typing import TYPE_CHECKING, Any

from easynetwork.servers.handlers import (
    BlockingDatagramClient,
    BlockingDatagramRequestHandler,
    BlockingStreamClient,
    BlockingStreamRequestHandler,
)
from easynetwork.servers.threaded_tcp import ThreadedTCPNetworkServer
from easynetwork.servers.threaded_udp import ThreadedUDPNetworkServer

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class FakeStreamHandler(BlockingStreamRequestHandler[Any, Any]):
    __slots__ = ()

    def handle(self, client: BlockingStreamClient[Any]) -> Generator[None, Any]:
        raise NotImplementedError


class FakeDatagramHandler(BlockingDatagramRequestHandler[Any, Any]):
    __slots__ = ()

    def handle(self, client: BlockingDatagramClient[Any]) -> Generator[None, Any]:
        raise NotImplementedError


class TestBlockingDatagramRequestHandler:
    @pytest.fixture
    @staticmethod
    def request_handler() -> BlockingDatagramRequestHandler[Any, Any]:
        return FakeDatagramHandler()

    @pytest.fixture
    @staticmethod
    def mock_server(mocker: MockerFixture) -> MagicMock:
        return mocker.NonCallableMagicMock(spec=ThreadedUDPNetworkServer)

    def test____service_init____return_None(
        self,
        request_handler: BlockingDatagramRequestHandler[Any, Any],
        mock_server: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        assert request_handler.service_init(contextlib.ExitStack(), mock_server) is None


class TestBlockingStreamRequestHandler:
    @pytest.fixture
    @staticmethod
    def request_handler() -> BlockingStreamRequestHandler[Any, Any]:
        return FakeStreamHandler()

    @pytest.fixture
    @staticmethod
    def mock_server(mocker: MockerFixture) -> MagicMock:
        return mocker.NonCallableMagicMock(spec=ThreadedTCPNetworkServer)

    def test____service_init____return_None(
        self,
        request_handler: BlockingStreamRequestHandler[Any, Any],
        mock_server: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        assert request_handler.service_init(contextlib.ExitStack(), mock_server) is None

    def test____on_connection____return_None(
        self,
        mock_stream_client: MagicMock,
        request_handler: BlockingStreamRequestHandler[Any, Any],
    ) -> None:
        # Arrange

        # Act & Assert
        assert request_handler.on_connection(mock_stream_client) is None

    def test____on_disconnection____return_None(
        self,
        mock_stream_client: MagicMock,
        request_handler: BlockingStreamRequestHandler[Any, Any],
    ) -> None:
        # Arrange

        # Act & Assert
        assert request_handler.on_disconnection(mock_stream_client) is None
