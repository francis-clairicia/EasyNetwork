# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Generator

from easynetwork.exceptions import (
    DatagramProtocolParseError,
    DeserializeError,
    IncrementalDeserializeError,
    PacketConversionError,
    StreamProtocolParseError,
)
from easynetwork.protocol import DatagramProtocol, StreamProtocol

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class TestDatagramProtocol:
    @pytest.fixture
    @staticmethod
    def protocol_without_converter(mock_serializer: MagicMock) -> DatagramProtocol[Any, Any]:
        return DatagramProtocol(mock_serializer, None)

    @pytest.fixture
    @staticmethod
    def protocol_with_converter(mock_serializer: MagicMock, mock_converter: MagicMock) -> DatagramProtocol[Any, Any]:
        return DatagramProtocol(mock_serializer, mock_converter)

    @pytest.fixture(params=["with_converter", "without_converter"])
    @staticmethod
    def protocol(
        request: Any, protocol_with_converter: DatagramProtocol[Any, Any], protocol_without_converter: DatagramProtocol[Any, Any]
    ) -> DatagramProtocol[Any, Any]:
        match request.param:
            case "with_converter":
                return protocol_with_converter
            case "without_converter":
                return protocol_without_converter
            case _:
                raise AssertionError("Invalid param")

    def test____make_datagram____without_converter(
        self,
        protocol_without_converter: DatagramProtocol[Any, Any],
        mock_serializer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_serialize_func: MagicMock = mock_serializer.serialize
        mock_serialize_func.return_value = mocker.sentinel.serialized_data

        # Act
        data = protocol_without_converter.make_datagram(mocker.sentinel.packet)

        # Assert
        mock_serialize_func.assert_called_once_with(mocker.sentinel.packet)
        assert data is mocker.sentinel.serialized_data

    def test____make_datagram____with_converter(
        self,
        protocol_with_converter: DatagramProtocol[Any, Any],
        mock_serializer: MagicMock,
        mock_converter: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_serialize_func: MagicMock = mock_serializer.serialize
        mock_serialize_func.return_value = mocker.sentinel.serialized_data
        mock_convert_func: MagicMock = mock_converter.convert_to_dto_packet
        mock_convert_func.return_value = mocker.sentinel.dto_packet

        # Act
        data = protocol_with_converter.make_datagram(mocker.sentinel.packet)

        # Assert
        mock_convert_func.assert_called_once_with(mocker.sentinel.packet)
        mock_serialize_func.assert_called_once_with(mocker.sentinel.dto_packet)
        assert data is mocker.sentinel.serialized_data

    def test____build_packet_from_datagram____without_converter(
        self,
        protocol_without_converter: DatagramProtocol[Any, Any],
        mock_serializer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_deserialize_func: MagicMock = mock_serializer.deserialize
        mock_deserialize_func.return_value = mocker.sentinel.packet

        # Act
        packet = protocol_without_converter.build_packet_from_datagram(mocker.sentinel.data)

        # Assert
        mock_deserialize_func.assert_called_once_with(mocker.sentinel.data)
        assert packet is mocker.sentinel.packet

    def test____build_packet_from_datagram____with_converter(
        self,
        protocol_with_converter: DatagramProtocol[Any, Any],
        mock_serializer: MagicMock,
        mock_converter: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_deserialize_func: MagicMock = mock_serializer.deserialize
        mock_deserialize_func.return_value = mocker.sentinel.dto_packet
        mock_convert_func: MagicMock = mock_converter.create_from_dto_packet
        mock_convert_func.return_value = mocker.sentinel.packet

        # Act
        packet = protocol_with_converter.build_packet_from_datagram(mocker.sentinel.data)

        # Assert
        mock_deserialize_func.assert_called_once_with(mocker.sentinel.data)
        mock_convert_func.assert_called_once_with(mocker.sentinel.dto_packet)
        assert packet is mocker.sentinel.packet

    def test____build_packet_from_datagram____deserialize_error(
        self,
        protocol: DatagramProtocol[Any, Any],
        mock_serializer: MagicMock,
        mock_converter: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_serializer.deserialize.side_effect = DeserializeError("Deserialization error", error_info=mocker.sentinel.error_info)
        mock_convert_func: MagicMock = mock_converter.create_from_dto_packet

        # Act
        with pytest.raises(DatagramProtocolParseError) as exc_info:
            _ = protocol.build_packet_from_datagram(mocker.sentinel.data)

        exception = exc_info.value

        # Assert
        mock_convert_func.assert_not_called()
        assert exception.error_type == "deserialization"
        assert exception.message == "Deserialization error"
        assert exception.error_info is mocker.sentinel.error_info
        assert exception.__cause__ is mock_serializer.deserialize.side_effect

    def test____build_packet_from_datagram____conversion_error(
        self,
        protocol_with_converter: DatagramProtocol[Any, Any],
        mock_converter: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_converter.create_from_dto_packet.side_effect = PacketConversionError(
            "Conversion error",
            error_info=mocker.sentinel.error_info,
        )
        mock_convert_func: MagicMock = mock_converter.create_from_dto_packet

        # Act
        with pytest.raises(DatagramProtocolParseError) as exc_info:
            _ = protocol_with_converter.build_packet_from_datagram(mocker.sentinel.data)

        exception = exc_info.value

        # Assert
        mock_convert_func.assert_called_once()
        assert exception.error_type == "conversion"
        assert exception.message == "Conversion error"
        assert exception.error_info is mocker.sentinel.error_info
        assert exception.__cause__ is mock_convert_func.side_effect


class TestStreamProtocol:
    sentinel: Any

    @pytest.fixture(autouse=True)
    def _bind_mocker_sentinel(self, mocker: MockerFixture) -> Generator[None, None, None]:
        self.sentinel = mocker.sentinel
        yield
        del self.sentinel

    @pytest.fixture
    @staticmethod
    def protocol_without_converter(mock_incremental_serializer: MagicMock) -> StreamProtocol[Any, Any]:
        return StreamProtocol(mock_incremental_serializer, None)

    @pytest.fixture
    @staticmethod
    def protocol_with_converter(mock_incremental_serializer: MagicMock, mock_converter: MagicMock) -> StreamProtocol[Any, Any]:
        return StreamProtocol(mock_incremental_serializer, mock_converter)

    @pytest.fixture(params=["with_converter", "without_converter"])
    @staticmethod
    def protocol(
        request: Any, protocol_with_converter: StreamProtocol[Any, Any], protocol_without_converter: StreamProtocol[Any, Any]
    ) -> StreamProtocol[Any, Any]:
        match request.param:
            case "with_converter":
                return protocol_with_converter
            case "without_converter":
                return protocol_without_converter
            case _:
                raise AssertionError("Invalid param")

    def generate_chunk_side_effect(self, packet: Any) -> Generator[bytes, None, None]:
        yield self.sentinel.chunk_a
        yield self.sentinel.chunk_b
        yield self.sentinel.chunk_c

    def build_packet_from_chunks_side_effect(self) -> Generator[None, bytes, tuple[Any, bytes]]:
        data = yield
        return self.sentinel.deserialized_packet, data

    def build_packet_from_chunks_side_effect_deserialize_error(self) -> Generator[None, bytes, tuple[Any, bytes]]:
        data = yield
        raise IncrementalDeserializeError("Deserialization error", data, error_info=self.sentinel.error_info)

    def test____generate_chunk____without_converter(
        self,
        protocol_without_converter: StreamProtocol[Any, Any],
        mock_incremental_serializer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_incremental_serialize_func: MagicMock = mock_incremental_serializer.incremental_serialize
        mock_incremental_serialize_func.side_effect = self.generate_chunk_side_effect

        # Act
        chunks: list[Any] = list(protocol_without_converter.generate_chunks(mocker.sentinel.packet))

        # Assert
        mock_incremental_serialize_func.assert_called_once_with(mocker.sentinel.packet)
        assert chunks == [mocker.sentinel.chunk_a, mocker.sentinel.chunk_b, mocker.sentinel.chunk_c]

    def test____generate_chunk____with_converter(
        self,
        protocol_with_converter: StreamProtocol[Any, Any],
        mock_incremental_serializer: MagicMock,
        mock_converter: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_incremental_serialize_func: MagicMock = mock_incremental_serializer.incremental_serialize
        mock_incremental_serialize_func.side_effect = self.generate_chunk_side_effect
        mock_convert_func: MagicMock = mock_converter.convert_to_dto_packet
        mock_convert_func.return_value = mocker.sentinel.dto_packet

        # Act
        chunks: list[Any] = list(protocol_with_converter.generate_chunks(mocker.sentinel.packet))

        # Assert
        mock_convert_func.assert_called_once_with(mocker.sentinel.packet)
        mock_incremental_serialize_func.assert_called_once_with(mocker.sentinel.dto_packet)
        assert chunks == [mocker.sentinel.chunk_a, mocker.sentinel.chunk_b, mocker.sentinel.chunk_c]

    def test____build_packet_from_chunks____without_converter(
        self,
        protocol_without_converter: StreamProtocol[Any, Any],
        mock_incremental_serializer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_incremental_deserialize_func: MagicMock = mock_incremental_serializer.incremental_deserialize
        mock_incremental_deserialize_func.side_effect = self.build_packet_from_chunks_side_effect

        # Act
        gen = protocol_without_converter.build_packet_from_chunks()
        next(gen)
        with pytest.raises(StopIteration) as exc_info:
            gen.send(mocker.sentinel.chunk)
        packet, remaining_data = exc_info.value.value

        # Assert
        mock_incremental_deserialize_func.assert_called_once_with()
        assert packet is mocker.sentinel.deserialized_packet
        assert remaining_data is mocker.sentinel.chunk

    def test____build_packet_from_chunks____with_converter(
        self,
        protocol_with_converter: StreamProtocol[Any, Any],
        mock_incremental_serializer: MagicMock,
        mock_converter: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_incremental_deserialize_func: MagicMock = mock_incremental_serializer.incremental_deserialize
        mock_incremental_deserialize_func.side_effect = self.build_packet_from_chunks_side_effect
        mock_convert_func: MagicMock = mock_converter.create_from_dto_packet
        mock_convert_func.return_value = mocker.sentinel.packet

        # Act
        gen = protocol_with_converter.build_packet_from_chunks()
        next(gen)
        with pytest.raises(StopIteration) as exc_info:
            gen.send(mocker.sentinel.chunk)
        packet, remaining_data = exc_info.value.value

        # Assert
        mock_incremental_deserialize_func.assert_called_once_with()
        mock_convert_func.assert_called_once_with(mocker.sentinel.deserialized_packet)
        assert packet is mocker.sentinel.packet
        assert remaining_data is mocker.sentinel.chunk

    def test____build_packet_from_chunks____deserialize_error(
        self,
        protocol: StreamProtocol[Any, Any],
        mock_incremental_serializer: MagicMock,
        mock_converter: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_incremental_deserialize_func: MagicMock = mock_incremental_serializer.incremental_deserialize
        mock_incremental_deserialize_func.side_effect = self.build_packet_from_chunks_side_effect_deserialize_error
        mock_convert_func: MagicMock = mock_converter.create_from_dto_packet

        # Act
        gen = protocol.build_packet_from_chunks()
        next(gen)
        with pytest.raises(StreamProtocolParseError) as exc_info:
            gen.send(mocker.sentinel.chunk)

        exception = exc_info.value

        # Assert
        mock_convert_func.assert_not_called()
        assert exception.error_type == "deserialization"
        assert exception.remaining_data is mocker.sentinel.chunk
        assert exception.message == "Deserialization error"
        assert exception.error_info is mocker.sentinel.error_info
        assert isinstance(exception.__cause__, DeserializeError)

    def test____build_packet_from_chunks____wrong_deserialize_error(
        self,
        protocol: StreamProtocol[Any, Any],
        mock_incremental_serializer: MagicMock,
        mock_converter: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def build_packet_from_chunks_side_effect_deserialize_error() -> Generator[None, bytes, tuple[Any, bytes]]:
            yield
            raise DeserializeError("Deserialization error", error_info=self.sentinel.error_info)

        mock_incremental_deserialize_func: MagicMock = mock_incremental_serializer.incremental_deserialize
        mock_incremental_deserialize_func.side_effect = build_packet_from_chunks_side_effect_deserialize_error
        mock_convert_func: MagicMock = mock_converter.create_from_dto_packet

        # Act
        gen = protocol.build_packet_from_chunks()
        next(gen)
        with pytest.raises(RuntimeError, match=r"^DeserializeError raised instead of IncrementalDeserializeError$"):
            gen.send(mocker.sentinel.chunk)

        # Assert
        mock_convert_func.assert_not_called()

    def test____build_packet_from_chunks____conversion_error(
        self,
        protocol_with_converter: StreamProtocol[Any, Any],
        mock_incremental_serializer: MagicMock,
        mock_converter: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_incremental_deserialize_func: MagicMock = mock_incremental_serializer.incremental_deserialize
        mock_incremental_deserialize_func.side_effect = self.build_packet_from_chunks_side_effect
        mock_convert_func: MagicMock = mock_converter.create_from_dto_packet
        mock_convert_func.side_effect = PacketConversionError("Conversion error", error_info=mocker.sentinel.error_info)

        # Act
        gen = protocol_with_converter.build_packet_from_chunks()
        next(gen)
        with pytest.raises(StreamProtocolParseError) as exc_info:
            gen.send(mocker.sentinel.chunk)

        exception = exc_info.value

        # Assert
        mock_convert_func.assert_called_once()
        assert exception.error_type == "conversion"
        assert exception.remaining_data is mocker.sentinel.chunk
        assert exception.message == "Conversion error"
        assert exception.error_info is mocker.sentinel.error_info
        assert exception.__cause__ is mock_convert_func.side_effect
