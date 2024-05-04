from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from easynetwork.exceptions import DatagramProtocolParseError, DeserializeError
from easynetwork.lowlevel.typed_attr import TypedAttributeProvider

import pytest

from .....base import BaseTestWithDatagramProtocol
from .._interfaces import SupportsClosing, SupportsReceiving, SupportsSending

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class BaseEndpointTests(BaseTestWithDatagramProtocol):
    @pytest.mark.parametrize("transport_closed", [False, True])
    def test____is_closed____default(
        self,
        endpoint: SupportsClosing,
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

    def test____close____default(
        self,
        endpoint: SupportsClosing,
        mock_datagram_transport: MagicMock,
    ) -> None:
        # Arrange
        mock_datagram_transport.close.assert_not_called()

        # Act
        endpoint.close()

        # Assert
        mock_datagram_transport.close.assert_called_once_with()

    def test____extra_attributes____default(
        self,
        endpoint: TypedAttributeProvider,
        mock_datagram_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_transport.extra_attributes = {mocker.sentinel.name: lambda: mocker.sentinel.extra_info}

        # Act
        value = endpoint.extra(mocker.sentinel.name)

        # Assert
        assert value is mocker.sentinel.extra_info


class BaseEndpointSendTests(BaseEndpointTests):
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

    def test____send_packet____send_bytes_to_transport(
        self,
        send_timeout: float | None,
        expected_send_timeout: float,
        endpoint: SupportsSending,
        mock_datagram_transport: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_transport.send.return_value = None

        # Act
        endpoint.send_packet(mocker.sentinel.packet, timeout=send_timeout)

        # Assert
        mock_datagram_protocol.make_datagram.assert_called_once_with(mocker.sentinel.packet)
        mock_datagram_transport.send.assert_called_once_with(b"packet", expected_send_timeout)

    def test____send_packet____protocol_crashed(
        self,
        endpoint: SupportsSending,
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


class BaseEndpointReceiveTests(BaseEndpointTests):
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

    def test____recv_packet____receive_bytes_from_transport(
        self,
        endpoint: SupportsReceiving,
        recv_timeout: float | None,
        expected_recv_timeout: float,
        mock_datagram_transport: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_transport.recv.side_effect = [b"packet"]

        # Act
        packet = endpoint.recv_packet(timeout=recv_timeout)

        # Assert
        mock_datagram_transport.recv.assert_called_once_with(expected_recv_timeout)
        mock_datagram_protocol.build_packet_from_datagram.assert_called_once_with(b"packet")
        assert packet is mocker.sentinel.packet

    def test____recv_packet____protocol_parse_error(
        self,
        endpoint: SupportsReceiving,
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

    def test____recv_packet____protocol_crashed(
        self,
        endpoint: SupportsReceiving,
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
