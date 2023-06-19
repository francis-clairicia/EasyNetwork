# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from easynetwork.converter import AbstractPacketConverterComposite, PacketConverterComposite, RequestResponseConverterBuilder

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class TestPacketConverterComposite:
    @pytest.fixture
    @staticmethod
    def create_from_dto_stub(mocker: MockerFixture) -> MagicMock:
        return mocker.MagicMock(spec=lambda packet: None, name="create_from_dto_stub")

    @pytest.fixture
    @staticmethod
    def convert_to_dto_stub(mocker: MockerFixture) -> MagicMock:
        return mocker.MagicMock(spec=lambda obj: None, name="convert_to_dto_stub")

    @pytest.fixture
    @staticmethod
    def converter(
        create_from_dto_stub: MagicMock,
        convert_to_dto_stub: MagicMock,
    ) -> PacketConverterComposite[Any, Any, Any, Any]:
        return PacketConverterComposite(convert_to_dto_stub, create_from_dto_stub)

    def test____create_from_dto_packet____callback(
        self,
        converter: PacketConverterComposite[Any, Any, Any, Any],
        create_from_dto_stub: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        create_from_dto_stub.return_value = mocker.sentinel.packet

        # Act
        packet = converter.create_from_dto_packet(mocker.sentinel.dto_packet)

        # Assert
        create_from_dto_stub.assert_called_once_with(mocker.sentinel.dto_packet)
        assert packet is mocker.sentinel.packet

    def test____convert_to_dto_packet____callback(
        self,
        converter: PacketConverterComposite[Any, Any, Any, Any],
        convert_to_dto_stub: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        convert_to_dto_stub.return_value = mocker.sentinel.dto_packet

        # Act
        dto_packet = converter.convert_to_dto_packet(mocker.sentinel.packet)

        # Assert
        convert_to_dto_stub.assert_called_once_with(mocker.sentinel.packet)
        assert dto_packet is mocker.sentinel.dto_packet


class TestRequestResponseConverterBuilder:
    @pytest.fixture
    @staticmethod
    def mock_request_converter(mock_converter_factory: Callable[[], MagicMock]) -> MagicMock:
        return mock_converter_factory()

    @pytest.fixture
    @staticmethod
    def mock_response_converter(mock_converter_factory: Callable[[], MagicMock]) -> MagicMock:
        return mock_converter_factory()

    def test____build_for_client____creates_composite_with_two_converters(
        self,
        mock_request_converter: MagicMock,
        mock_response_converter: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_request_converter.convert_to_dto_packet.return_value = mocker.sentinel.dto_request
        mock_response_converter.create_from_dto_packet.return_value = mocker.sentinel.response

        # Act
        converter: AbstractPacketConverterComposite[Any, Any, Any, Any]
        converter = RequestResponseConverterBuilder.build_for_client(mock_request_converter, mock_response_converter)
        dto_request = converter.convert_to_dto_packet(mocker.sentinel.request)
        response = converter.create_from_dto_packet(mocker.sentinel.dto_response)

        # Assert
        assert dto_request is mocker.sentinel.dto_request
        assert response is mocker.sentinel.response
        mock_request_converter.convert_to_dto_packet.assert_called_once_with(mocker.sentinel.request)
        mock_response_converter.create_from_dto_packet.assert_called_once_with(mocker.sentinel.dto_response)
        mock_request_converter.create_from_dto_packet.assert_not_called()
        mock_response_converter.convert_to_dto_packet.assert_not_called()

    def test____build_for_server____creates_composite_with_two_converters(
        self,
        mock_request_converter: MagicMock,
        mock_response_converter: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_request_converter.create_from_dto_packet.return_value = mocker.sentinel.request
        mock_response_converter.convert_to_dto_packet.return_value = mocker.sentinel.dto_response

        # Act
        converter: AbstractPacketConverterComposite[Any, Any, Any, Any]
        converter = RequestResponseConverterBuilder.build_for_server(mock_request_converter, mock_response_converter)
        request = converter.create_from_dto_packet(mocker.sentinel.dto_request)
        dto_response = converter.convert_to_dto_packet(mocker.sentinel.response)

        # Assert
        assert request is mocker.sentinel.request
        assert dto_response is mocker.sentinel.dto_response
        mock_request_converter.create_from_dto_packet.assert_called_once_with(mocker.sentinel.dto_request)
        mock_response_converter.convert_to_dto_packet.assert_called_once_with(mocker.sentinel.response)
        mock_request_converter.convert_to_dto_packet.assert_not_called()
        mock_response_converter.create_from_dto_packet.assert_not_called()
