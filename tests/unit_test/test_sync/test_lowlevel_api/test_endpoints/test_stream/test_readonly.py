from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from easynetwork.lowlevel.api_sync.endpoints.stream import StreamReceiverEndpoint
from easynetwork.lowlevel.api_sync.transports.abc import StreamReadTransport

import pytest

from ....mock_tools import make_transport_mock
from .base import BaseEndpointReceiveTests

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class TestStreamReceiverEndpoint(BaseEndpointReceiveTests):
    @pytest.fixture
    @staticmethod
    def mock_stream_transport(mocker: MockerFixture) -> MagicMock:
        return make_transport_mock(mocker=mocker, spec=StreamReadTransport)

    @pytest.fixture
    @staticmethod
    def endpoint(
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
    ) -> Iterator[StreamReceiverEndpoint[Any]]:
        endpoint: StreamReceiverEndpoint[Any] = StreamReceiverEndpoint(
            mock_stream_transport,
            mock_stream_protocol,
            max_recv_size,
        )
        with endpoint:
            yield endpoint

    def test____dunder_init____invalid_transport(
        self,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_invalid_transport = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a StreamReadTransport object, got .*$"):
            _ = StreamReceiverEndpoint(mock_invalid_transport, mock_stream_protocol, max_recv_size)

    def test____dunder_init____invalid_protocol(
        self,
        mock_stream_transport: MagicMock,
        max_recv_size: int,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_invalid_protocol = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a StreamProtocol or a BufferedStreamProtocol object, got .*$"):
            _ = StreamReceiverEndpoint(mock_stream_transport, mock_invalid_protocol, max_recv_size)

    @pytest.mark.parametrize("max_recv_size", [0, -1, 10.4], ids=lambda p: f"max_recv_size=={p}")
    def test____dunder_init____max_recv_size____invalid_value(
        self,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: Any,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^'max_recv_size' must be a strictly positive integer$"):
            _ = StreamReceiverEndpoint(mock_stream_transport, mock_stream_protocol, max_recv_size)

    def test____dunder_del____ResourceWarning(
        self,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
    ) -> None:
        # Arrange
        endpoint: StreamReceiverEndpoint[Any] = StreamReceiverEndpoint(
            mock_stream_transport,
            mock_stream_protocol,
            max_recv_size,
        )

        # Act & Assert
        with pytest.warns(ResourceWarning, match=r"^unclosed endpoint .+$"):
            del endpoint

        mock_stream_transport.close.assert_called()
