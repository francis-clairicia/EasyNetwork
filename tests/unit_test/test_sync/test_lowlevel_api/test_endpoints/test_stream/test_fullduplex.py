from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from easynetwork.exceptions import UnsupportedOperation
from easynetwork.lowlevel.api_sync.endpoints.stream import StreamEndpoint
from easynetwork.lowlevel.api_sync.transports.abc import BufferedStreamReadTransport, StreamTransport

import pytest

from ....mock_tools import make_transport_mock
from .base import BaseEndpointReceiveTests, BaseEndpointSendTests

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class BufferedStreamTransport(StreamTransport, BufferedStreamReadTransport):
    __slots__ = ()


class TestStreamEndpoint(BaseEndpointSendTests, BaseEndpointReceiveTests):
    @pytest.fixture(params=["recv_data", "recv_buffer"])
    @staticmethod
    def mock_stream_transport(request: pytest.FixtureRequest, mocker: MockerFixture) -> MagicMock:
        match request.param:
            case "recv_data":
                return make_transport_mock(mocker=mocker, spec=StreamTransport)
            case "recv_buffer":
                return make_transport_mock(mocker=mocker, spec=BufferedStreamTransport)
            case _:
                pytest.fail("Invalid stream transport parameter")

    @pytest.fixture
    @staticmethod
    def endpoint(
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
    ) -> Iterator[StreamEndpoint[Any, Any]]:
        try:
            endpoint: StreamEndpoint[Any, Any] = StreamEndpoint(mock_stream_transport, mock_stream_protocol, max_recv_size)
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
        with pytest.raises(TypeError, match=r"^Expected a StreamTransport object, got .*$"):
            _ = StreamEndpoint(mock_invalid_transport, mock_stream_protocol, max_recv_size)

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
            _ = StreamEndpoint(mock_stream_transport, mock_invalid_protocol, max_recv_size)

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
        endpoint: StreamEndpoint[Any, Any] = StreamEndpoint(mock_stream_transport, mock_stream_protocol, max_recv_size)
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
            _ = StreamEndpoint(mock_stream_transport, mock_stream_protocol, max_recv_size)

    @pytest.mark.parametrize("mock_stream_transport", ["recv_buffer"], indirect=True)
    def test____dunder_del____ResourceWarning(
        self,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
    ) -> None:
        # Arrange
        endpoint: StreamEndpoint[Any, Any] = StreamEndpoint(
            mock_stream_transport,
            mock_stream_protocol,
            max_recv_size,
        )

        # Act & Assert
        with pytest.warns(ResourceWarning, match=r"^unclosed endpoint .+$"):
            del endpoint

        mock_stream_transport.close.assert_called()

    @pytest.mark.parametrize("transport_closed", [False, True], ids=lambda p: f"transport_closed=={p}")
    def test____send_eof____default(
        self,
        transport_closed: bool,
        endpoint: StreamEndpoint[Any, Any],
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.is_closed.return_value = transport_closed

        # Act
        endpoint.send_eof()

        # Assert
        mock_stream_transport.send_eof.assert_called_once_with()
        with pytest.raises(RuntimeError, match=r"^send_eof\(\) has been called earlier$"):
            endpoint.send_packet(mocker.sentinel.packet)
        mock_stream_protocol.generate_chunks.assert_not_called()
        mock_stream_transport.send_all_from_iterable.assert_not_called()

    @pytest.mark.parametrize("transport_closed", [False, True], ids=lambda p: f"transport_closed=={p}")
    def test____send_eof____idempotent(
        self,
        transport_closed: bool,
        endpoint: StreamEndpoint[Any, Any],
        mock_stream_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.is_closed.return_value = transport_closed
        endpoint.send_eof()

        # Act
        endpoint.send_eof()

        # Assert
        mock_stream_transport.send_eof.assert_called_once_with()
        with pytest.raises(RuntimeError, match=r"^send_eof\(\) has been called earlier$"):
            endpoint.send_packet(mocker.sentinel.packet)

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
            _ = StreamEndpoint(mock_stream_transport, mock_stream_protocol, max_recv_size)
