# -*- coding: Utf-8 -*

from __future__ import annotations

from abc import ABCMeta, abstractmethod
from typing import Any, final

from easynetwork.serializers.abc import AbstractPacketSerializer
from easynetwork.serializers.exceptions import DeserializeError
from easynetwork.serializers.stream.abc import AbstractIncrementalPacketSerializer
from easynetwork.serializers.stream.exceptions import IncrementalDeserializeError

import pytest

from ..._utils import send_return


class BaseTestSerializer(metaclass=ABCMeta):
    @classmethod
    @abstractmethod
    def get_oneshot_serialize_sample(cls) -> list[tuple[Any, bytes, str]]:
        raise NotImplementedError

    @classmethod
    def get_invalid_complete_data(cls) -> list[tuple[bytes, str]]:
        return []

    @final
    def test____serialize____sample(
        self,
        serializer: AbstractPacketSerializer[Any, Any],
        packet: Any,
        expected_data: bytes,
    ) -> None:
        # Arrange

        # Act
        data = serializer.serialize(packet)

        # Assert
        assert isinstance(data, bytes)
        assert data == expected_data

    @final
    def test____deserialize____sample(
        self,
        serializer: AbstractPacketSerializer[Any, Any],
        data: bytes,
        expected_packet: Any,
    ) -> None:
        # Arrange

        # Act
        packet = serializer.deserialize(data)

        # Assert
        assert type(packet) is type(expected_packet)
        assert packet == expected_packet

    def test____deserialize____invalid_data(
        self,
        serializer: AbstractPacketSerializer[Any, Any],
        invalid_complete_data: bytes,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(DeserializeError):
            _ = serializer.deserialize(invalid_complete_data)


class BaseTestIncrementalSerializer(BaseTestSerializer):
    @classmethod
    @abstractmethod
    def get_incremental_serialize_sample(cls) -> list[tuple[Any, bytes, str]]:
        raise NotImplementedError

    @classmethod
    def get_invalid_partial_data(cls) -> list[tuple[bytes, bytes, str]]:
        return []

    @final
    def test____incremental_serialize____concatenated_chunks(
        self,
        serializer: AbstractIncrementalPacketSerializer[Any, Any],
        packet: Any,
        expected_data: bytes,
    ) -> None:
        # Arrange

        # Act
        data: bytes = b"".join(serializer.incremental_serialize(packet))

        # Assert
        assert isinstance(data, bytes)
        assert data == expected_data

    @final
    def test____incremental_deserialize____one_shot_chunk(
        self,
        serializer: AbstractIncrementalPacketSerializer[Any, Any],
        data: bytes,
        expected_packet: Any,
    ) -> None:
        # Arrange
        consumer = serializer.incremental_deserialize()
        next(consumer)

        # Act
        packet, remaining_data = send_return(consumer, data)

        # Assert
        assert isinstance(remaining_data, bytes)
        assert remaining_data == b""
        assert type(packet) is type(expected_packet)
        assert packet == expected_packet

    @final
    def test____incremental_deserialize____with_remaining_data(
        self,
        serializer: AbstractIncrementalPacketSerializer[Any, Any],
        data: bytes,
        expected_packet: Any,
        expected_remaining_data: bytes,
    ) -> None:
        # Arrange
        consumer = serializer.incremental_deserialize()
        next(consumer)

        # Act
        packet, remaining_data = send_return(consumer, data + expected_remaining_data)

        # Assert
        assert isinstance(remaining_data, bytes)
        assert remaining_data == expected_remaining_data
        assert type(packet) is type(expected_packet)
        assert packet == expected_packet

    @final
    @pytest.mark.parametrize("empty_bytes_before", [False, True], ids=lambda boolean: f"empty_bytes_before=={boolean}")
    def test____incremental_deserialize____give_chunk_byte_per_byte(
        self,
        serializer: AbstractIncrementalPacketSerializer[Any, Any],
        empty_bytes_before: bool,
        data: bytes,
        expected_packet: Any,
    ) -> None:
        # Arrange
        import struct

        chunks_list: list[bytes] = list(struct.unpack(f"{len(data)}c", data))
        assert all(len(b) == 1 for b in chunks_list) and b"".join(chunks_list) == data

        del data, struct

        consumer = serializer.incremental_deserialize()
        next(consumer)

        # Act
        with pytest.raises(StopIteration) as exc_info:
            # The generator can stop at any moment (no need to go to the last byte)
            # However, the remaining data returned should be empty
            for chunk in chunks_list:
                if empty_bytes_before:
                    consumer.send(b"")
                consumer.send(chunk)

        packet, remaining_data = exc_info.value.value

        # Assert
        assert isinstance(remaining_data, bytes)
        assert remaining_data == b""
        assert type(packet) is type(expected_packet)
        assert packet == expected_packet

    def test____incremental_deserialize____invalid_data(
        self,
        serializer: AbstractIncrementalPacketSerializer[Any, Any],
        invalid_partial_data: bytes,
        expected_remaining_data: bytes,
    ) -> None:
        # Arrange
        consumer = serializer.incremental_deserialize()
        next(consumer)

        # Act
        with pytest.raises(IncrementalDeserializeError) as exc_info:
            consumer.send(invalid_partial_data)
        exception = exc_info.value

        # Assert
        assert exception.remaining_data == expected_remaining_data


@final
class NoSerialization(AbstractPacketSerializer[bytes, bytes]):
    """Helper for serializer wrapper"""

    def serialize(self, packet: bytes) -> bytes:
        return packet

    def deserialize(self, data: bytes) -> bytes:
        return data
