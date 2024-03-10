from __future__ import annotations

import contextlib
import math
from typing import TYPE_CHECKING, Any

from easynetwork.exceptions import DatagramProtocolParseError, DeserializeError, UnsupportedOperation
from easynetwork.lowlevel.api_sync.endpoints.datagram import DatagramEndpoint
from easynetwork.lowlevel.api_sync.transports.abc import DatagramReadTransport, DatagramTransport, DatagramWriteTransport

import pytest

from ....base import BaseTestWithDatagramProtocol

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class TestDatagramEndpoint(BaseTestWithDatagramProtocol):
    @pytest.fixture(params=[DatagramReadTransport, DatagramWriteTransport, DatagramTransport])
    @staticmethod
    def mock_datagram_transport(request: pytest.FixtureRequest, mocker: MockerFixture) -> MagicMock:
        mock_datagram_transport = mocker.NonCallableMagicMock(spec=request.param)
        mock_datagram_transport.is_closed.return_value = False

        def close_side_effect() -> None:
            mock_datagram_transport.is_closed.return_value = True

        mock_datagram_transport.close.side_effect = close_side_effect
        return mock_datagram_transport

    @pytest.fixture
    @staticmethod
    def endpoint(mock_datagram_transport: MagicMock, mock_datagram_protocol: MagicMock) -> DatagramEndpoint[Any, Any]:
        return DatagramEndpoint(mock_datagram_transport, mock_datagram_protocol)

    @pytest.fixture(
        params=[
            pytest.param(None, id="blocking (None)"),
            pytest.param(math.inf, id="blocking (+inf)"),
            pytest.param(0, id="non_blocking"),
            pytest.param(123456789, id="with_timeout"),
        ]
    )
    @staticmethod
    def recv_timeout(request: Any) -> Any:
        return request.param

    @pytest.fixture
    @staticmethod
    def expected_recv_timeout(recv_timeout: float | None) -> float:
        if recv_timeout is None:
            return math.inf
        return recv_timeout

    @pytest.fixture(
        params=[
            pytest.param(None, id="blocking (None)"),
            pytest.param(math.inf, id="blocking (+inf)"),
            pytest.param(0, id="non_blocking"),
            pytest.param(123456789, id="with_timeout"),
        ]
    )
    @staticmethod
    def send_timeout(request: Any) -> Any:
        return request.param

    @pytest.fixture
    @staticmethod
    def expected_send_timeout(send_timeout: float | None) -> float:
        if send_timeout is None:
            return math.inf
        return send_timeout

    def test____dunder_init____invalid_transport(
        self,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_invalid_transport = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a DatagramTransport object, got .*$"):
            _ = DatagramEndpoint(mock_invalid_transport, mock_datagram_protocol)

    def test____dunder_init____invalid_protocol(
        self,
        mock_datagram_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_invalid_protocol = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a DatagramProtocol object, got .*$"):
            _ = DatagramEndpoint(mock_datagram_transport, mock_invalid_protocol)

    @pytest.mark.parametrize("transport_closed", [False, True])
    def test____is_closed____default(
        self,
        endpoint: DatagramEndpoint[Any, Any],
        mock_datagram_transport: MagicMock,
        transport_closed: bool,
    ) -> None:
        # Arrange
        mock_datagram_transport.is_closed.assert_not_called()
        mock_datagram_transport.is_closed.return_value = transport_closed

        # Act
        state = endpoint.is_closed()

        # Assert
        mock_datagram_transport.is_closed.assert_called_once_with()
        assert state is transport_closed

    def test____close____default(self, endpoint: DatagramEndpoint[Any, Any], mock_datagram_transport: MagicMock) -> None:
        # Arrange
        mock_datagram_transport.close.assert_not_called()

        # Act
        endpoint.close()

        # Assert
        mock_datagram_transport.close.assert_called_once_with()

    def test____extra_attributes____default(
        self,
        endpoint: DatagramEndpoint[Any, Any],
        mock_datagram_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_transport.extra_attributes = {mocker.sentinel.name: lambda: mocker.sentinel.extra_info}

        # Act
        value = endpoint.extra(mocker.sentinel.name)

        # Assert
        assert value is mocker.sentinel.extra_info

    def test____send_packet____send_bytes_to_transport(
        self,
        send_timeout: float | None,
        expected_send_timeout: float,
        endpoint: DatagramEndpoint[Any, Any],
        mock_datagram_transport: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        with contextlib.suppress(AttributeError):
            mock_datagram_transport.send.return_value = None

        # Act
        with (
            pytest.raises(UnsupportedOperation, match=r"^transport does not support sending data$")
            if mock_datagram_transport.__class__ not in (DatagramWriteTransport, DatagramTransport)
            else contextlib.nullcontext()
        ):
            endpoint.send_packet(mocker.sentinel.packet, timeout=send_timeout)

        # Assert
        if mock_datagram_transport.__class__ in (DatagramWriteTransport, DatagramTransport):
            mock_datagram_protocol.make_datagram.assert_called_once_with(mocker.sentinel.packet)
            mock_datagram_transport.send.assert_called_once_with(b"packet", expected_send_timeout)
        else:
            mock_datagram_protocol.make_datagram.assert_not_called()

    @pytest.mark.parametrize("mock_datagram_transport", [DatagramWriteTransport], indirect=True)
    def test____send_packet____protocol_crashed(
        self,
        endpoint: DatagramEndpoint[Any, Any],
        send_timeout: float | None,
        mock_datagram_transport: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_transport.send.return_value = None
        expected_error = Exception("Error")
        mock_datagram_protocol.make_datagram.side_effect = expected_error

        # Act
        with pytest.raises(RuntimeError, match=r"^protocol\.make_datagram\(\) crashed$") as exc_info:
            endpoint.send_packet(mocker.sentinel.packet, timeout=send_timeout)

        # Assert
        assert exc_info.value.__cause__ is expected_error
        mock_datagram_transport.send.assert_not_called()

    def test____recv_packet____receive_bytes_from_transport(
        self,
        endpoint: DatagramEndpoint[Any, Any],
        recv_timeout: float | None,
        expected_recv_timeout: float,
        mock_datagram_transport: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        with contextlib.suppress(AttributeError):
            mock_datagram_transport.recv.side_effect = [b"packet"]

        # Act
        packet: Any = mocker.sentinel.packet_not_received
        with (
            pytest.raises(UnsupportedOperation, match=r"^transport does not support receiving data$")
            if mock_datagram_transport.__class__ not in (DatagramReadTransport, DatagramTransport)
            else contextlib.nullcontext()
        ):
            packet = endpoint.recv_packet(timeout=recv_timeout)

        # Assert
        if mock_datagram_transport.__class__ in (DatagramReadTransport, DatagramTransport):
            mock_datagram_transport.recv.assert_called_once_with(expected_recv_timeout)
            mock_datagram_protocol.build_packet_from_datagram.assert_called_once_with(b"packet")
            assert packet is mocker.sentinel.packet
        else:
            mock_datagram_protocol.build_packet_from_datagram.assert_not_called()
            assert packet is mocker.sentinel.packet_not_received

    @pytest.mark.parametrize("mock_datagram_transport", [DatagramReadTransport], indirect=True)
    def test____recv_packet____protocol_parse_error(
        self,
        endpoint: DatagramEndpoint[Any, Any],
        recv_timeout: float | None,
        mock_datagram_transport: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange
        mock_datagram_transport.recv.side_effect = [b"packet"]
        expected_error = DatagramProtocolParseError(DeserializeError("Invalid packet"))
        mock_datagram_protocol.build_packet_from_datagram.side_effect = expected_error

        # Act
        with pytest.raises(DatagramProtocolParseError) as exc_info:
            endpoint.recv_packet(timeout=recv_timeout)

        # Assert
        assert exc_info.value is expected_error

    @pytest.mark.parametrize("mock_datagram_transport", [DatagramReadTransport], indirect=True)
    def test____recv_packet____protocol_crashed(
        self,
        endpoint: DatagramEndpoint[Any, Any],
        recv_timeout: float | None,
        mock_datagram_transport: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange
        mock_datagram_transport.recv.side_effect = [b"packet"]
        expected_error = Exception("Error")
        mock_datagram_protocol.build_packet_from_datagram.side_effect = expected_error

        # Act
        with pytest.raises(RuntimeError, match=r"^protocol\.build_packet_from_datagram\(\) crashed$") as exc_info:
            endpoint.recv_packet(timeout=recv_timeout)

        # Assert
        assert exc_info.value.__cause__ is expected_error
