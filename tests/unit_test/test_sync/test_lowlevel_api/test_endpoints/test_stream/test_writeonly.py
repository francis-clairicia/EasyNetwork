from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from easynetwork.lowlevel.api_sync.endpoints.stream import StreamSenderEndpoint
from easynetwork.lowlevel.api_sync.transports.abc import StreamWriteTransport

import pytest

from ....mock_tools import make_transport_mock
from .base import BaseEndpointSendTests

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class TestStreamSenderEndpoint(BaseEndpointSendTests):
    @pytest.fixture
    @staticmethod
    def mock_stream_transport(mocker: MockerFixture) -> MagicMock:
        return make_transport_mock(mocker=mocker, spec=StreamWriteTransport)

    @pytest.fixture
    @staticmethod
    def endpoint(
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
    ) -> Iterator[StreamSenderEndpoint[Any]]:
        with StreamSenderEndpoint[Any](mock_stream_transport, mock_stream_protocol) as endpoint:
            yield endpoint

    def test____dunder_init____invalid_transport(
        self,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_invalid_transport = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a StreamWriteTransport object, got .*$"):
            _ = StreamSenderEndpoint(mock_invalid_transport, mock_stream_protocol)

    def test____dunder_init____invalid_protocol(
        self,
        mock_stream_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_invalid_protocol = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a StreamProtocol or a BufferedStreamProtocol object, got .*$"):
            _ = StreamSenderEndpoint(mock_stream_transport, mock_invalid_protocol)

    def test____dunder_del____ResourceWarning(
        self,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
    ) -> None:
        # Arrange
        endpoint: StreamSenderEndpoint[Any] = StreamSenderEndpoint(
            mock_stream_transport,
            mock_stream_protocol,
        )

        # Act & Assert
        with pytest.warns(ResourceWarning, match=r"^unclosed endpoint .+$"):
            del endpoint

        mock_stream_transport.close.assert_called()
