# -*- coding: Utf-8 -*

from __future__ import annotations

from abc import ABCMeta, abstractmethod
from typing import Any, final

from easynetwork.serializers.abc import AbstractPacketSerializer
from easynetwork.serializers.stream.abc import AbstractIncrementalPacketSerializer

import pytest


class BaseTestSerializer(metaclass=ABCMeta):
    @classmethod
    @abstractmethod
    def get_oneshot_serialize_sample(cls) -> list[tuple[Any, bytes] | tuple[Any, bytes, str]]:
        raise NotImplementedError

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


class BaseTestIncrementalSerializer(BaseTestSerializer):
    @classmethod
    @abstractmethod
    def get_incremental_serialize_sample(cls) -> list[tuple[Any, bytes] | tuple[Any, bytes, str]]:
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def get_possible_remaining_data(cls) -> list[bytes | tuple[bytes, str]]:
        raise NotImplementedError

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
        with pytest.raises(StopIteration) as exc_info:
            consumer.send(data)

        packet, remaining_data = exc_info.value.value

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
        with pytest.raises(StopIteration) as exc_info:
            consumer.send(data + expected_remaining_data)

        packet, remaining_data = exc_info.value.value

        # Assert
        assert isinstance(remaining_data, bytes)
        assert remaining_data == expected_remaining_data
        assert type(packet) is type(expected_packet)
        assert packet == expected_packet

    @final
    def test____incremental_deserialize____give_chunk_byte_per_byte(
        self,
        serializer: AbstractIncrementalPacketSerializer[Any, Any],
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
                consumer.send(chunk)

        packet, remaining_data = exc_info.value.value

        # Assert
        assert isinstance(remaining_data, bytes)
        assert remaining_data == b""
        assert type(packet) is type(expected_packet)
        assert packet == expected_packet
