from __future__ import annotations

from typing import TYPE_CHECKING

from easynetwork.api_async.server.udp import AsyncUDPNetworkServer

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock


@pytest.mark.asyncio
class TestAsyncUDPNetworkServer:
    async def test____dunder_init____protocol____invalid_value(
        self,
        mock_stream_protocol: MagicMock,
        mock_datagram_request_handler: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a DatagramProtocol object, got .*$"):
            _ = AsyncUDPNetworkServer("localhost", 0, mock_stream_protocol, mock_datagram_request_handler)

    async def test____dunder_init____request_handler____invalid_value(
        self,
        mock_datagram_protocol: MagicMock,
        mock_stream_request_handler: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected an AsyncDatagramRequestHandler object, got .*$"):
            _ = AsyncUDPNetworkServer("localhost", 0, mock_datagram_protocol, mock_stream_request_handler)
