from __future__ import annotations

import random
import weakref
from abc import ABCMeta
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, final

from easynetwork.exceptions import DeserializeError, IncrementalDeserializeError
from easynetwork.lowlevel._utils import iter_bytes
from easynetwork.serializers.abc import (
    AbstractIncrementalPacketSerializer,
    AbstractPacketSerializer,
    BufferedIncrementalPacketSerializer,
)

import pytest

from ...tools import send_return, write_data_and_extra_in_buffer, write_in_buffer

if TYPE_CHECKING:
    from _typeshed import WriteableBuffer


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
        assert isinstance(serializer_for_serialization, AbstractPacketSerializer)
        assert isinstance(serializer_for_deserialization, AbstractPacketSerializer)
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
        assert isinstance(data, bytes)
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


class BaseTestSerializerExtraData(BaseTestSerializer):
    @pytest.fixture(scope="class")
    @staticmethod
    def oneshot_extra_data() -> bytes:
        return b"remaining_data"

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
    def invalid_partial_data_extra_data() -> tuple[bytes, bytes]:
        return (b"remaining_data", b"remaining_data")

    def test____fixture____consistency____incremental_serializer(
        self,
        serializer_for_serialization: AbstractIncrementalPacketSerializer[Any, Any],
        serializer_for_deserialization: AbstractIncrementalPacketSerializer[Any, Any],
    ) -> None:
        assert isinstance(serializer_for_serialization, AbstractIncrementalPacketSerializer)
        assert isinstance(serializer_for_deserialization, AbstractIncrementalPacketSerializer)

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
        assert isinstance(remaining_data, bytes)
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
        assert isinstance(remaining_data, bytes)
        assert remaining_data == incremental_extra_data
        assert type(packet) is type(packet_to_serialize)
        assert packet == packet_to_serialize

    def test____incremental_deserialize____give_chunk_byte_per_byte(
        self,
        serializer_for_deserialization: AbstractIncrementalPacketSerializer[Any, Any],
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
                consumer.send(chunk)

        packet, remaining_data = exc_info.value.value

        # Assert
        assert isinstance(remaining_data, bytes)
        assert remaining_data == b""
        assert type(packet) is type(packet_to_serialize)
        assert packet == packet_to_serialize

    def test____incremental_deserialize____invalid_data(
        self,
        serializer_for_deserialization: AbstractIncrementalPacketSerializer[Any, Any],
        invalid_partial_data: bytes,
        invalid_partial_data_extra_data: tuple[bytes, bytes],
    ) -> None:
        # Arrange
        sent_extra_data, expected_remainder = invalid_partial_data_extra_data
        del invalid_partial_data_extra_data
        consumer = serializer_for_deserialization.incremental_deserialize()
        next(consumer)

        # Act
        with pytest.raises(IncrementalDeserializeError) as exc_info:
            consumer.send(invalid_partial_data + sent_extra_data)
        exception = exc_info.value

        # Assert
        assert bytes(exception.remaining_data) == expected_remainder


class BaseTestBufferedIncrementalSerializer(BaseTestIncrementalSerializer):
    def test____fixture____consistency____incremental_serializer(
        self,
        serializer_for_serialization: AbstractIncrementalPacketSerializer[Any, Any],
        serializer_for_deserialization: AbstractIncrementalPacketSerializer[Any, Any],
    ) -> None:
        super().test____fixture____consistency____incremental_serializer(
            serializer_for_serialization=serializer_for_serialization,
            serializer_for_deserialization=serializer_for_deserialization,
        )
        assert isinstance(serializer_for_serialization, BufferedIncrementalPacketSerializer)
        assert isinstance(serializer_for_deserialization, BufferedIncrementalPacketSerializer)

    def test____buffered_incremental_deserialize____one_shot_chunk(
        self,
        serializer_for_deserialization: BufferedIncrementalPacketSerializer[Any, Any, WriteableBuffer],
        complete_data_for_incremental_deserialize: bytes,
        packet_to_serialize: Any,
    ) -> None:
        # Arrange
        buffer = serializer_for_deserialization.create_deserializer_buffer(len(complete_data_for_incremental_deserialize))
        consumer = serializer_for_deserialization.buffered_incremental_deserialize(buffer)
        start_idx = next(consumer)
        nbytes = write_in_buffer(
            buffer,
            complete_data_for_incremental_deserialize,
            start_pos=start_idx,
            too_short_buffer="xfail",
        )

        # Act
        packet, remaining_data = send_return(consumer, nbytes)

        # Assert
        assert bytes(remaining_data) == b""
        assert type(packet) is type(packet_to_serialize)
        assert packet == packet_to_serialize

    def test____buffered_incremental_deserialize____with_remaining_data(
        self,
        serializer_for_deserialization: BufferedIncrementalPacketSerializer[Any, Any, WriteableBuffer],
        complete_data_for_incremental_deserialize: bytes,
        packet_to_serialize: Any,
        incremental_extra_data: bytes,
    ) -> None:
        # Arrange
        assert len(incremental_extra_data) > 0
        buffer = serializer_for_deserialization.create_deserializer_buffer(
            len(complete_data_for_incremental_deserialize) + len(incremental_extra_data) + 1024
        )
        consumer = serializer_for_deserialization.buffered_incremental_deserialize(buffer)
        start_idx = next(consumer)
        nbytes, expected_remaining_data = write_data_and_extra_in_buffer(
            buffer,
            complete_data_for_incremental_deserialize,
            incremental_extra_data,
            start_pos=start_idx,
            too_short_buffer_for_complete_data="xfail",
        )
        assert len(expected_remaining_data) > 0
        assert incremental_extra_data.startswith(expected_remaining_data)

        # Act
        packet, remaining_data = send_return(consumer, nbytes)

        # Assert
        assert memoryview(remaining_data) == expected_remaining_data
        assert type(packet) is type(packet_to_serialize)
        assert packet == packet_to_serialize

    def test____buffered_incremental_deserialize____give_chunk_byte_per_byte(
        self,
        serializer_for_deserialization: BufferedIncrementalPacketSerializer[Any, Any, WriteableBuffer],
        complete_data_for_incremental_deserialize: bytes,
        packet_to_serialize: Any,
    ) -> None:
        # Arrange
        buffer = serializer_for_deserialization.create_deserializer_buffer(len(complete_data_for_incremental_deserialize))
        consumer = serializer_for_deserialization.buffered_incremental_deserialize(buffer)
        start_idx = next(consumer)

        # Act
        with pytest.raises(StopIteration) as exc_info:
            # The generator can stop at any moment (no need to go to the last byte)
            # However, the remaining data returned should be empty
            for chunk in iter_bytes(complete_data_for_incremental_deserialize):
                nbytes = write_in_buffer(buffer, chunk, start_pos=start_idx)
                assert nbytes == 1
                start_idx = consumer.send(nbytes)

        packet, remaining_data = exc_info.value.value

        # Assert
        assert bytes(remaining_data) == b""
        assert type(packet) is type(packet_to_serialize)
        assert packet == packet_to_serialize

    def test____buffered_incremental_deserialize____invalid_data(
        self,
        serializer_for_deserialization: BufferedIncrementalPacketSerializer[Any, Any, WriteableBuffer],
        invalid_partial_data: bytes,
        invalid_partial_data_extra_data: tuple[bytes, bytes],
    ) -> None:
        # Arrange
        sent_extra_data, expected_remainder = invalid_partial_data_extra_data
        del invalid_partial_data_extra_data
        buffer = serializer_for_deserialization.create_deserializer_buffer(
            len(invalid_partial_data) + len(sent_extra_data) + 1024
        )
        consumer = serializer_for_deserialization.buffered_incremental_deserialize(buffer)
        start_idx = next(consumer)
        nbytes, partial_remaining_data = write_data_and_extra_in_buffer(
            buffer,
            invalid_partial_data,
            sent_extra_data,
            start_pos=start_idx,
            too_short_buffer_for_complete_data="fill_at_most",
        )
        expected_remainder = expected_remainder.replace(sent_extra_data, partial_remaining_data, 1)
        del partial_remaining_data

        # Act
        with pytest.raises(IncrementalDeserializeError) as exc_info:
            consumer.send(nbytes)
        exception = exc_info.value

        # Assert
        assert bytes(exception.remaining_data) == expected_remainder


@final
class NoSerialization(AbstractPacketSerializer[bytes, bytes]):
    """Helper for serializer wrapper"""

    def serialize(self, packet: bytes) -> bytes:
        return packet

    def deserialize(self, data: bytes) -> bytes:
        return data
