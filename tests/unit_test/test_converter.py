from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from easynetwork.converter import StapledPacketConverter

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class TestStapledPacketConverter:
    @pytest.fixture
    @staticmethod
    def mock_sent_packet_converter(mock_converter_factory: Callable[[], MagicMock]) -> MagicMock:
        return mock_converter_factory()

    @pytest.fixture
    @staticmethod
    def mock_received_packet_converter(mock_converter_factory: Callable[[], MagicMock]) -> MagicMock:
        return mock_converter_factory()

    @pytest.fixture
    @staticmethod
    def converter(
        mock_sent_packet_converter: MagicMock,
        mock_received_packet_converter: MagicMock,
    ) -> StapledPacketConverter[Any, Any, Any, Any]:
        return StapledPacketConverter(mock_sent_packet_converter, mock_received_packet_converter)

    def test____create_from_dto_packet____default(
        self,
        converter: StapledPacketConverter[Any, Any, Any, Any],
        mock_sent_packet_converter: MagicMock,
        mock_received_packet_converter: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_received_packet_converter.create_from_dto_packet.return_value = mocker.sentinel.packet

        # Act
        packet = converter.create_from_dto_packet(mocker.sentinel.dto_packet)

        # Assert
        mock_sent_packet_converter.convert_to_dto_packet.assert_not_called()
        mock_sent_packet_converter.create_from_dto_packet.assert_not_called()
        mock_received_packet_converter.convert_to_dto_packet.assert_not_called()
        mock_received_packet_converter.create_from_dto_packet.assert_called_once_with(mocker.sentinel.dto_packet)
        assert packet is mocker.sentinel.packet

    def test____convert_to_dto_packet____callback(
        self,
        converter: StapledPacketConverter[Any, Any, Any, Any],
        mock_sent_packet_converter: MagicMock,
        mock_received_packet_converter: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_sent_packet_converter.convert_to_dto_packet.return_value = mocker.sentinel.dto_packet

        # Act
        dto_packet = converter.convert_to_dto_packet(mocker.sentinel.packet)

        # Assert
        mock_sent_packet_converter.convert_to_dto_packet.assert_called_once_with(mocker.sentinel.packet)
        mock_sent_packet_converter.create_from_dto_packet.assert_not_called()
        mock_received_packet_converter.convert_to_dto_packet.assert_not_called()
        mock_received_packet_converter.create_from_dto_packet.assert_not_called()
        assert dto_packet is mocker.sentinel.dto_packet
