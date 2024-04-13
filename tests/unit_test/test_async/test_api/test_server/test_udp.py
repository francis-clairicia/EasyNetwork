from __future__ import annotations

from typing import TYPE_CHECKING, Any

from easynetwork.servers.async_udp import AsyncUDPNetworkServer

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.mark.asyncio
class TestAsyncUDPNetworkServer:
    @pytest.fixture
    @staticmethod
    def server(
        mock_datagram_protocol: MagicMock,
        mock_datagram_request_handler: MagicMock,
        mock_backend: MagicMock,
    ) -> AsyncUDPNetworkServer[Any, Any]:
        return AsyncUDPNetworkServer(None, 0, mock_datagram_protocol, mock_datagram_request_handler, mock_backend)

    async def test____dunder_init____protocol____invalid_value(
        self,
        mock_stream_protocol: MagicMock,
        mock_datagram_request_handler: MagicMock,
        mock_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a DatagramProtocol object, got .*$"):
            _ = AsyncUDPNetworkServer("localhost", 0, mock_stream_protocol, mock_datagram_request_handler, mock_backend)

    async def test____dunder_init____request_handler____invalid_value(
        self,
        mock_datagram_protocol: MagicMock,
        mock_stream_request_handler: MagicMock,
        mock_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected an AsyncDatagramRequestHandler object, got .*$"):
            _ = AsyncUDPNetworkServer("localhost", 0, mock_datagram_protocol, mock_stream_request_handler, mock_backend)

    async def test____dunder_init____backend____invalid_value(
        self,
        mock_datagram_protocol: MagicMock,
        mock_datagram_request_handler: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        invalid_backend = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected an AsyncBackend instance, got .*$"):
            _ = AsyncUDPNetworkServer(None, 0, mock_datagram_protocol, mock_datagram_request_handler, invalid_backend)

    async def test____get_backend____returns_linked_instance(
        self,
        server: AsyncUDPNetworkServer[Any, Any],
        mock_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        assert server.backend() is mock_backend
