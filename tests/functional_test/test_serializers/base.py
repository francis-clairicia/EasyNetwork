# -*- coding: utf-8 -*

from __future__ import annotations

import random
from abc import ABCMeta
from typing import Any, Callable, final

from easynetwork.exceptions import DeserializeError, IncrementalDeserializeError
from easynetwork.serializers.abc import AbstractIncrementalPacketSerializer, AbstractPacketSerializer
from easynetwork.tools._utils import iter_bytes

import pytest

from ...tools import send_return


class BaseTestSerializer(metaclass=ABCMeta):
    @pytest.fixture(scope="class")
    @staticmethod
    def oneshot_extra_data() -> bytes:
        return b"remaining_data"

    #### Invalid data

    @pytest.fixture(scope="class")
    @staticmethod
    def invalid_complete_data() -> bytes:
        return random.randbytes(32)

    def test____fixture____consistency(
        self,
        serializer_for_serialization: AbstractPacketSerializer[Any, Any],
        serializer_for_deserialization: AbstractPacketSerializer[Any, Any],
    ) -> None:
        assert type(serializer_for_serialization) is type(serializer_for_deserialization)

    def test____slots____no_dict(
        self,
        serializer_for_serialization: AbstractPacketSerializer[Any, Any],
        serializer_for_deserialization: AbstractPacketSerializer[Any, Any],
    ) -> None:
        assert not hasattr(serializer_for_serialization, "__dict__")
        assert not hasattr(serializer_for_deserialization, "__dict__")

    def test____slots____weakref(
        self,
        serializer_for_serialization: AbstractPacketSerializer[Any, Any],
        serializer_for_deserialization: AbstractPacketSerializer[Any, Any],
    ) -> None:
        import weakref

        assert weakref.ref(serializer_for_serialization)() is serializer_for_serialization
        assert weakref.ref(serializer_for_deserialization)() is serializer_for_deserialization

    def test____serialize____sample(
        self,
        serializer_for_serialization: AbstractPacketSerializer[Any, Any],
        packet_to_serialize: Any,
        expected_complete_data: bytes | Callable[[bytes], None],
    ) -> None:
        # Arrange

        # Act
        data = serializer_for_serialization.serialize(packet_to_serialize)

        # Assert
        assert isinstance(data, (bytes, bytearray))
        if callable(expected_complete_data):
            expected_complete_data(data)
        else:
            assert data == expected_complete_data

    def test____deserialize____sample(
        self,
        serializer_for_deserialization: AbstractPacketSerializer[Any, Any],
        complete_data: bytes,
        packet_to_serialize: Any,
    ) -> None:
        # Arrange

        # Act
        packet = serializer_for_deserialization.deserialize(complete_data)

        # Assert
        assert type(packet) is type(packet_to_serialize)
        assert packet == packet_to_serialize

    def test____deserialize____invalid_data(
        self,
        serializer_for_deserialization: AbstractPacketSerializer[Any, Any],
        invalid_complete_data: bytes,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(DeserializeError):
            _ = serializer_for_deserialization.deserialize(invalid_complete_data)

    def test____deserialize____extra_data(
        self,
        serializer_for_deserialization: AbstractPacketSerializer[Any, Any],
        complete_data: bytes,
        oneshot_extra_data: bytes,
    ) -> None:
        # Arrange
        assert len(oneshot_extra_data) > 0

        # Act & Assert
        with pytest.raises(DeserializeError):
            _ = serializer_for_deserialization.deserialize(complete_data + oneshot_extra_data)


class BaseTestIncrementalSerializer(BaseTestSerializer):
    @pytest.fixture(scope="class")
    @staticmethod
    def incremental_extra_data() -> bytes:
        return b"remaining_data"

    @pytest.fixture(scope="class")
    @staticmethod
    def invalid_partial_data() -> bytes:
        return random.randbytes(32)

    @pytest.fixture(scope="class")
    @staticmethod
    def invalid_partial_data_extra_data() -> bytes | None:
        return b"remaining_data"

    def test____incremental_serialize____concatenated_chunks(
        self,
        serializer_for_serialization: AbstractIncrementalPacketSerializer[Any, Any],
        packet_to_serialize: Any,
        expected_joined_data: bytes | Callable[[bytes], None],
    ) -> None:
        # Arrange

        # Act
        data: bytes = b"".join(serializer_for_serialization.incremental_serialize(packet_to_serialize))

        # Assert
        if callable(expected_joined_data):
            expected_joined_data(data)
        else:
            assert data == expected_joined_data

    def test____incremental_deserialize____one_shot_chunk(
        self,
        serializer_for_deserialization: AbstractIncrementalPacketSerializer[Any, Any],
        complete_data_for_incremental_deserialize: bytes,
        packet_to_serialize: Any,
    ) -> None:
        # Arrange
        consumer = serializer_for_deserialization.incremental_deserialize()
        next(consumer)

        # Act
        packet, remaining_data = send_return(consumer, complete_data_for_incremental_deserialize)

        # Assert
        assert isinstance(remaining_data, (bytes, bytearray))
        assert remaining_data == b""
        assert type(packet) is type(packet_to_serialize)
        assert packet == packet_to_serialize

    def test____incremental_deserialize____with_remaining_data(
        self,
        serializer_for_deserialization: AbstractIncrementalPacketSerializer[Any, Any],
        complete_data_for_incremental_deserialize: bytes,
        packet_to_serialize: Any,
        incremental_extra_data: bytes,
    ) -> None:
        # Arrange
        assert len(incremental_extra_data) > 0
        consumer = serializer_for_deserialization.incremental_deserialize()
        next(consumer)

        # Act
        packet, remaining_data = send_return(consumer, complete_data_for_incremental_deserialize + incremental_extra_data)

        # Assert
        assert isinstance(remaining_data, (bytes, bytearray))
        assert remaining_data == incremental_extra_data
        assert type(packet) is type(packet_to_serialize)
        assert packet == packet_to_serialize

    @pytest.mark.parametrize("empty_bytes_before", [False, True], ids=lambda boolean: f"empty_bytes_before=={boolean}")
    def test____incremental_deserialize____give_chunk_byte_per_byte(
        self,
        serializer_for_deserialization: AbstractIncrementalPacketSerializer[Any, Any],
        empty_bytes_before: bool,
        complete_data_for_incremental_deserialize: bytes,
        packet_to_serialize: Any,
    ) -> None:
        # Arrange

        consumer = serializer_for_deserialization.incremental_deserialize()
        next(consumer)

        # Act
        with pytest.raises(StopIteration) as exc_info:
            # The generator can stop at any moment (no need to go to the last byte)
            # However, the remaining data returned should be empty
            for chunk in iter_bytes(complete_data_for_incremental_deserialize):
                assert len(chunk) == 1
                if empty_bytes_before:
                    try:
                        consumer.send(b"")
                    except StopIteration:
                        raise RuntimeError("consumer stopped when sending empty bytes")
                consumer.send(chunk)

        packet, remaining_data = exc_info.value.value

        # Assert
        assert isinstance(remaining_data, (bytes, bytearray))
        assert remaining_data == b""
        assert type(packet) is type(packet_to_serialize)
        assert packet == packet_to_serialize

    def test____incremental_deserialize____invalid_data(
        self,
        serializer_for_deserialization: AbstractIncrementalPacketSerializer[Any, Any],
        invalid_partial_data: bytes,
        invalid_partial_data_extra_data: bytes | None,
    ) -> None:
        # Arrange
        consumer = serializer_for_deserialization.incremental_deserialize()
        next(consumer)

        # Act
        with pytest.raises(IncrementalDeserializeError) as exc_info:
            if invalid_partial_data_extra_data:
                consumer.send(invalid_partial_data + invalid_partial_data_extra_data)
            else:
                consumer.send(invalid_partial_data)
        exception = exc_info.value

        # Assert
        if invalid_partial_data_extra_data is not None:
            assert exception.remaining_data == invalid_partial_data_extra_data
        else:
            assert len(exception.remaining_data) > 0


@final
class NoSerialization(AbstractPacketSerializer[bytes, bytes]):
    """Helper for serializer wrapper"""

    def serialize(self, packet: bytes) -> bytes:
        return packet

    def deserialize(self, data: bytes) -> bytes:
        return data
