from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from easynetwork.lowlevel.api_sync.endpoints.stream import StreamEndpoint
from easynetwork.lowlevel.api_sync.transports.abc import StreamTransport

import pytest

from ....._utils import make_recv_into_side_effect
from ....mock_tools import make_transport_mock
from .base import BaseEndpointReceiveTests, BaseEndpointSendTests

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class TestStreamEndpoint(BaseEndpointSendTests, BaseEndpointReceiveTests):
    @pytest.fixture
    @staticmethod
    def mock_stream_transport(mocker: MockerFixture) -> MagicMock:
        return make_transport_mock(mocker=mocker, spec=StreamTransport)

    @pytest.fixture
    @staticmethod
    def endpoint(
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
    ) -> Iterator[StreamEndpoint[Any, Any]]:
        endpoint: StreamEndpoint[Any, Any] = StreamEndpoint(mock_stream_transport, mock_stream_protocol, max_recv_size)
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

    @pytest.mark.parametrize("stream_protocol_mode", ["data"], indirect=True)
    def test____special_case____send_packet____eof_error____still_try_socket_send(
        self,
        send_timeout: float | None,
        expected_send_timeout: float,
        recv_timeout: float | None,
        endpoint: StreamEndpoint[Any, Any],
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        chunks: list[bytes] = []
        mock_stream_transport.send_all_from_iterable.side_effect = lambda it, timeout: chunks.extend(it)
        mock_stream_transport.recv.side_effect = [b""]
        with pytest.raises(ConnectionAbortedError):
            _ = endpoint.recv_packet(timeout=recv_timeout)

        mock_stream_transport.recv.reset_mock()

        # Act
        endpoint.send_packet(mocker.sentinel.packet, timeout=send_timeout)

        # Assert
        mock_stream_protocol.generate_chunks.assert_called_with(mocker.sentinel.packet)
        mock_stream_transport.send_all_from_iterable.assert_called_once_with(mocker.ANY, expected_send_timeout)
        mock_stream_transport.send_all.assert_not_called()
        mock_stream_transport.send.assert_not_called()
        assert chunks == [b"packet\n"]

    @pytest.mark.parametrize("stream_protocol_mode", ["buffer"], indirect=True)
    def test____special_case____send_packet____eof_error____recv_buffered____still_try_socket_send(
        self,
        send_timeout: float | None,
        expected_send_timeout: float,
        recv_timeout: float | None,
        endpoint: StreamEndpoint[Any, Any],
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        chunks: list[bytes] = []
        mock_stream_transport.send_all_from_iterable.side_effect = lambda it, timeout: chunks.extend(it)
        mock_stream_transport.recv_into.side_effect = make_recv_into_side_effect([b""])
        with pytest.raises(ConnectionAbortedError):
            _ = endpoint.recv_packet(timeout=recv_timeout)

        mock_stream_transport.recv_into.reset_mock()

        # Act
        endpoint.send_packet(mocker.sentinel.packet, timeout=send_timeout)

        # Assert
        mock_stream_protocol.generate_chunks.assert_called_with(mocker.sentinel.packet)
        mock_stream_transport.send_all_from_iterable.assert_called_once_with(mocker.ANY, expected_send_timeout)
        mock_stream_transport.send_all.assert_not_called()
        mock_stream_transport.send.assert_not_called()
        assert chunks == [b"packet\n"]
