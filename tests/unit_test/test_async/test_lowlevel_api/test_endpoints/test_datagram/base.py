from __future__ import annotations

from typing import TYPE_CHECKING

from easynetwork.exceptions import DatagramProtocolParseError, DeserializeError
from easynetwork.lowlevel.typed_attr import TypedAttributeProvider

import pytest

from .....base import BaseTestWithDatagramProtocol
from .._interfaces import HaveBackend, SupportsClosing, SupportsReceiving, SupportsSending

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.mark.asyncio
class BaseAsyncEndpointTests(BaseTestWithDatagramProtocol):
    @pytest.mark.parametrize("transport_closed", [False, True])
    async def test____is_closing____default(
        self,
        endpoint: SupportsClosing,
        mock_datagram_transport: MagicMock,
        transport_closed: bool,
    ) -> None:
        # Arrange
        mock_datagram_transport.is_closing.assert_not_called()
        mock_datagram_transport.is_closing.return_value = transport_closed

        # Act
        state = endpoint.is_closing()

        # Assert
        mock_datagram_transport.is_closing.assert_called_once_with()
        assert state is transport_closed

    async def test____aclose____default(
        self,
        endpoint: SupportsClosing,
        mock_datagram_transport: MagicMock,
    ) -> None:
        # Arrange
        mock_datagram_transport.aclose.assert_not_called()

        # Act
        await endpoint.aclose()

        # Assert
        mock_datagram_transport.aclose.assert_awaited_once_with()

    async def test____extra_attributes____default(
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

    async def test____get_backend____returns_inner_transport_backend(
        self,
        endpoint: HaveBackend,
        mock_datagram_transport: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        assert endpoint.backend() is mock_datagram_transport.backend()


class BaseAsyncEndpointSenderTests(BaseAsyncEndpointTests):
    async def test____send_packet____send_bytes_to_transport(
        self,
        endpoint: SupportsSending,
        mock_datagram_transport: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_transport.send.return_value = None

        # Act
        await endpoint.send_packet(mocker.sentinel.packet)

        # Assert
        mock_datagram_protocol.make_datagram.assert_called_once_with(mocker.sentinel.packet)
        mock_datagram_transport.send.assert_awaited_once_with(b"packet")

    async def test____send_packet____protocol_crashed(
        self,
        endpoint: SupportsSending,
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
            await endpoint.send_packet(mocker.sentinel.packet)

        # Assert
        assert exc_info.value.__cause__ is expected_error
        mock_datagram_transport.send.assert_not_called()


class BaseAsyncEndpointReceiverTests(BaseAsyncEndpointTests):
    async def test____recv_packet____receive_bytes_from_transport(
        self,
        endpoint: SupportsReceiving,
        mock_datagram_transport: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_transport.recv.side_effect = [b"packet"]

        # Act
        packet = await endpoint.recv_packet()

        # Assert
        mock_datagram_transport.recv.assert_awaited_once_with()
        mock_datagram_protocol.build_packet_from_datagram.assert_called_once_with(b"packet")
        assert packet is mocker.sentinel.packet

    async def test____recv_packet____protocol_parse_error(
        self,
        endpoint: SupportsReceiving,
        mock_datagram_transport: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange
        mock_datagram_transport.recv.side_effect = [b"packet"]
        expected_error = DatagramProtocolParseError(DeserializeError("Invalid packet"))
        mock_datagram_protocol.build_packet_from_datagram.side_effect = expected_error

        # Act
        with pytest.raises(DatagramProtocolParseError) as exc_info:
            await endpoint.recv_packet()

        # Assert
        assert exc_info.value is expected_error

    async def test____recv_packet____protocol_crashed(
        self,
        endpoint: SupportsReceiving,
        mock_datagram_transport: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange
        mock_datagram_transport.recv.side_effect = [b"packet"]
        expected_error = Exception("Error")
        mock_datagram_protocol.build_packet_from_datagram.side_effect = expected_error

        # Act
        with pytest.raises(RuntimeError, match=r"^protocol\.build_packet_from_datagram\(\) crashed$") as exc_info:
            await endpoint.recv_packet()

        # Assert
        assert exc_info.value.__cause__ is expected_error
