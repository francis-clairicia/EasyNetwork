from __future__ import annotations

from typing import TYPE_CHECKING, Any

from easynetwork.servers.async_tcp import AsyncTCPNetworkServer

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.mark.asyncio
class TestAsyncTCPNetworkServer:
    @pytest.fixture
    @staticmethod
    def server(
        mock_stream_protocol: MagicMock,
        mock_stream_request_handler: MagicMock,
        mock_backend: MagicMock,
    ) -> AsyncTCPNetworkServer[Any, Any]:
        return AsyncTCPNetworkServer(None, 0, mock_stream_protocol, mock_stream_request_handler, mock_backend)

    async def test____dunder_init____protocol____invalid_value(
        self,
        mock_datagram_protocol: MagicMock,
        mock_stream_request_handler: MagicMock,
        mock_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a StreamProtocol object, got .*$"):
            _ = AsyncTCPNetworkServer(None, 0, mock_datagram_protocol, mock_stream_request_handler, mock_backend)

    async def test____dunder_init____request_handler____invalid_value(
        self,
        mock_stream_protocol: MagicMock,
        mock_datagram_request_handler: MagicMock,
        mock_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected an AsyncStreamRequestHandler object, got .*$"):
            _ = AsyncTCPNetworkServer(None, 0, mock_stream_protocol, mock_datagram_request_handler, mock_backend)

    @pytest.mark.parametrize("manual_buffer_allocation", ["unknown", ""], ids=lambda p: f"manual_buffer_allocation=={p!r}")
    async def test____dunder_init____manual_buffer_allocation____invalid_value(
        self,
        manual_buffer_allocation: Any,
        mock_stream_protocol: MagicMock,
        mock_stream_request_handler: MagicMock,
        mock_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r'^"manual_buffer_allocation" must be "try", "no" or "force"$'):
            _ = AsyncTCPNetworkServer(
                None,
                0,
                mock_stream_protocol,
                mock_stream_request_handler,
                mock_backend,
                manual_buffer_allocation=manual_buffer_allocation,
            )

    async def test____dunder_init____backend____invalid_value(
        self,
        mock_stream_protocol: MagicMock,
        mock_stream_request_handler: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        invalid_backend = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected an AsyncBackend instance, got .*$"):
            _ = AsyncTCPNetworkServer(None, 0, mock_stream_protocol, mock_stream_request_handler, invalid_backend)

    async def test____get_backend____returns_linked_instance(
        self,
        server: AsyncTCPNetworkServer[Any, Any],
        mock_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        assert server.backend() is mock_backend
