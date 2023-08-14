from __future__ import annotations

from typing import TYPE_CHECKING

from easynetwork.api_async.server.udp import AsyncUDPNetworkServer

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.mark.asyncio
class TestAsyncUDPNetworkServer:
    async def test____dunder_init____protocol____invalid_value(
        self,
        mock_stream_protocol: MagicMock,
        mock_request_handler: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a DatagramProtocol object, got .*$"):
            _ = AsyncUDPNetworkServer(None, 0, mock_stream_protocol, mock_request_handler)

    async def test____dunder_init____request_handler____invalid_value(
        self,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_invalid_request_handler = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected an AsyncBaseRequestHandler object, got .*$"):
            _ = AsyncUDPNetworkServer(None, 0, mock_datagram_protocol, mock_invalid_request_handler)
