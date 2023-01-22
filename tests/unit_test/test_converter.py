# -*- coding: Utf-8 -*-

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from easynetwork.converter import PacketConverterComposite

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
        return PacketConverterComposite(create_from_dto_stub, convert_to_dto_stub)

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
