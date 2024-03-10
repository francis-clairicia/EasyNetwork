from __future__ import annotations

from typing import TYPE_CHECKING, Any

from easynetwork.servers.async_tcp import AsyncTCPNetworkServer

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock


@pytest.mark.asyncio
class TestAsyncTCPNetworkServer:
    async def test____dunder_init____protocol____invalid_value(
        self,
        mock_datagram_protocol: MagicMock,
        mock_stream_request_handler: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a StreamProtocol object, got .*$"):
            _ = AsyncTCPNetworkServer(None, 0, mock_datagram_protocol, mock_stream_request_handler)

    async def test____dunder_init____request_handler____invalid_value(
        self,
        mock_stream_protocol: MagicMock,
        mock_datagram_request_handler: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected an AsyncStreamRequestHandler object, got .*$"):
            _ = AsyncTCPNetworkServer(None, 0, mock_stream_protocol, mock_datagram_request_handler)

    @pytest.mark.parametrize("manual_buffer_allocation", ["unknown", ""], ids=lambda p: f"manual_buffer_allocation=={p!r}")
    async def test____dunder_init____manual_buffer_allocation____invalid_value(
        self,
        manual_buffer_allocation: Any,
        mock_stream_protocol: MagicMock,
        mock_stream_request_handler: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r'^"manual_buffer_allocation" must be "try", "no" or "force"$'):
            _ = AsyncTCPNetworkServer(
                None,
                0,
                mock_stream_protocol,
                mock_stream_request_handler,
                manual_buffer_allocation=manual_buffer_allocation,
            )
