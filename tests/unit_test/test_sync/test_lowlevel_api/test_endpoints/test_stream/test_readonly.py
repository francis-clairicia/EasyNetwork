from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from easynetwork.exceptions import UnsupportedOperation
from easynetwork.lowlevel.api_sync.endpoints.stream import StreamReceiverEndpoint
from easynetwork.lowlevel.api_sync.transports.abc import BufferedStreamReadTransport, StreamReadTransport

import pytest

from ....mock_tools import make_transport_mock
from .base import BaseEndpointReceiveTests

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class TestStreamReceiverEndpoint(BaseEndpointReceiveTests):
    @pytest.fixture(params=["recv_data", "recv_buffer"])
    @staticmethod
    def mock_stream_transport(request: pytest.FixtureRequest, mocker: MockerFixture) -> MagicMock:
        match request.param:
            case "recv_data":
                return make_transport_mock(mocker=mocker, spec=StreamReadTransport)
            case "recv_buffer":
                return make_transport_mock(mocker=mocker, spec=BufferedStreamReadTransport)
            case _:
                pytest.fail("Invalid stream transport parameter")

    @pytest.fixture
    @staticmethod
    def endpoint(
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
    ) -> Iterator[StreamReceiverEndpoint[Any]]:
        try:
            endpoint: StreamReceiverEndpoint[Any] = StreamReceiverEndpoint(
                mock_stream_transport,
                mock_stream_protocol,
                max_recv_size,
            )
        except UnsupportedOperation:
            pytest.skip("Skip unsupported combination")
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

    @pytest.mark.parametrize("mock_stream_transport", ["recv_buffer"], indirect=True)
    @pytest.mark.parametrize("max_recv_size", [1, 2**16], ids=lambda p: f"max_recv_size=={p}")
    def test____dunder_init____max_recv_size____valid_value(
        self,
        request: pytest.FixtureRequest,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
    ) -> None:
        # Arrange

        # Act
        endpoint: StreamReceiverEndpoint[Any] = StreamReceiverEndpoint(mock_stream_transport, mock_stream_protocol, max_recv_size)
        request.addfinalizer(endpoint.close)

        # Assert
        assert endpoint.max_recv_size == max_recv_size

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

    @pytest.mark.parametrize("mock_stream_transport", ["recv_buffer"], indirect=True)
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

    @pytest.mark.parametrize("mock_stream_transport", ["recv_data"], indirect=True)
    @pytest.mark.parametrize("stream_protocol_mode", ["buffer"], indirect=True)
    def test____manual_buffer_allocation____but_stream_transport_does_not_support_it(
        self,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(
            UnsupportedOperation,
            match=r"^The transport implementation .+ does not implement BufferedStreamReadTransport interface$",
        ):
            _ = StreamReceiverEndpoint(
                mock_stream_transport,
                mock_stream_protocol,
                max_recv_size,
            )
