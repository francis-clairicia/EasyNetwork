# -*- coding: Utf-8 -*-

from __future__ import annotations

import json
from typing import Any, Callable

from easynetwork.serializers.json import JSONSerializer
from easynetwork.serializers.wrapper.compressor import (
    AbstractCompressorSerializer,
    BZ2CompressorSerializer,
    ZlibCompressorSerializer,
)

import pytest

from .base import BaseTestStreamIncrementalPacketDeserializer, DeserializerConsumer


@pytest.fixture
def json_data() -> Any:
    return {
        "data1": True,
        "data2": [
            {
                "user": "something",
                "password": "other_thing",
            }
        ],
        "data3": {
            "value": [1, 2, 3, 4],
            "salt": "azerty",
        },
        "data4": 3.14,
        "data5": [
            float("+inf"),
            float("-inf"),
            None,
        ],
    }


@pytest.fixture(scope="module")
def json_encoder() -> json.JSONEncoder:
    return json.JSONEncoder()


@pytest.fixture(params=[BZ2CompressorSerializer, ZlibCompressorSerializer])
def compressor_serializer(request: Any, json_encoder: json.JSONEncoder) -> AbstractCompressorSerializer[Any, Any]:
    factory: Callable[[Any], AbstractCompressorSerializer[Any, Any]] = request.param
    return factory(JSONSerializer(encoder=json_encoder))


@pytest.fixture
def json_data_bytes(json_encoder: json.JSONEncoder, json_data: Any) -> bytes:
    return json_encoder.encode(json_data).encode("utf-8")


@pytest.mark.functional
def test____serialize_deserialize____works(
    compressor_serializer: AbstractCompressorSerializer[Any, Any],
    json_data: Any,
    json_data_bytes: bytes,
) -> None:
    # Arrange

    # Act
    serialized_data = compressor_serializer.serialize(json_data)
    deserialized_data = compressor_serializer.deserialize(serialized_data)

    # Assert
    assert serialized_data != json_data_bytes
    assert len(serialized_data) < len(json_data_bytes)
    assert deserialized_data == json_data


class TestIncrementalDeserialize(BaseTestStreamIncrementalPacketDeserializer):
    def test____incremental_deserialize____one_shot_chunk(
        self,
        compressor_serializer: AbstractCompressorSerializer[Any, Any],
        json_data: Any,
    ) -> None:
        # Arrange
        deserializer_consumer: DeserializerConsumer[Any] = compressor_serializer.incremental_deserialize()
        next(deserializer_consumer)

        # Act
        serialized_data = b"".join(compressor_serializer.incremental_serialize(json_data))
        deserialized_data, remaining = self.deserialize_for_test(deserializer_consumer, serialized_data)

        # Assert
        assert serialized_data == compressor_serializer.serialize(json_data)
        assert deserialized_data == json_data
        assert isinstance(remaining, bytes)
        assert not remaining

    def test____incremental_deserialize____handle_partial_document(
        self,
        compressor_serializer: AbstractCompressorSerializer[Any, Any],
        json_data: Any,
    ) -> None:
        # Arrange
        import struct

        deserializer_consumer: DeserializerConsumer[Any] = compressor_serializer.incremental_deserialize()
        next(deserializer_consumer)

        serialized_data = b"".join(compressor_serializer.incremental_serialize(json_data))
        bytes_sequence: tuple[bytes, ...] = struct.unpack(f"{len(serialized_data)}c", serialized_data)

        # Act
        for chunk in bytes_sequence[:-1]:
            with pytest.raises(EOFError):
                _ = self.deserialize_for_test(deserializer_consumer, chunk)
        output, remainder = self.deserialize_for_test(deserializer_consumer, bytes_sequence[-1])

        # Assert
        assert not remainder
        assert output == json_data
