# -*- coding: Utf-8 -*-

from __future__ import annotations

import math
from typing import Any

from easynetwork.serializers.cbor import CBORSerializer

import pytest

from .base import BaseTestStreamIncrementalPacketDeserializer, DeserializerConsumer

SERIALIZE_PARAMS: list[tuple[Any, bytes]] = [
    ([], b"\x80"),
    ([1, 2, 3], b"\x83\x01\x02\x03"),
    ({}, b"\xa0"),
    ({"k": "v", "k2": "v2"}, b"\xa2akavbk2bv2"),  # No whitespaces by default
]

INCREMENTAL_SERIALIZE_PARAMS: list[tuple[Any, bytes]] = [(data, output) for data, output in SERIALIZE_PARAMS]

DESERIALIZE_PARAMS: list[tuple[bytes, Any]] = [(output, data) for data, output in SERIALIZE_PARAMS]

INCREMENTAL_DESERIALIZE_PARAMS: list[tuple[bytes, Any]] = [(output, data) for data, output in INCREMENTAL_SERIALIZE_PARAMS] + [
    (
        b"\x84\xa1evalueaa\xa1evalue\xfb@\t\x1e\xb8Q\xeb\x85\x1f\xa1evalue\xf5\xa1evalue\xa1eother\x81\xf9|\x00",
        [{"value": "a"}, {"value": 3.14}, {"value": True}, {"value": {"other": [float("+inf")]}}],
    ),
    (
        b"\xa2ckey\x81\xa2ckeyevaluedkey2\x83\x04\x05\xf9\xfc\x00eother\xf6",
        {"key": [{"key": "value", "key2": [4, 5, float("-inf")]}], "other": None},
    ),
    (
        b'\xa1xE{"key": [{"key": "value", "key2": [4, 5, -Infinity]}], "other": null}\x18*',
        {'{"key": [{"key": "value", "key2": [4, 5, -Infinity]}], "other": null}': 42},
    ),
]


@pytest.fixture
def serializer() -> CBORSerializer[Any, Any]:
    return CBORSerializer()


class TestCBORPacketSerializer:
    @pytest.mark.parametrize(["data", "expected_output"], SERIALIZE_PARAMS)
    def test____serialize(self, serializer: CBORSerializer[Any, Any], data: Any, expected_output: bytes) -> None:
        # Arrange

        # Act
        output = serializer.serialize(data)

        # Assert
        assert isinstance(output, bytes)
        assert output == expected_output

    @pytest.mark.parametrize(["data", "expected_output"], INCREMENTAL_SERIALIZE_PARAMS)
    def test____incremental_serialize(self, serializer: CBORSerializer[Any, Any], data: Any, expected_output: bytes) -> None:
        # Arrange

        # Act
        output = b"".join(serializer.incremental_serialize(data))

        # Assert
        assert isinstance(output, bytes)
        assert output == expected_output


class TestCBORPacketDeserializer(BaseTestStreamIncrementalPacketDeserializer):
    @pytest.fixture
    @staticmethod
    def consumer(serializer: CBORSerializer[Any, Any]) -> DeserializerConsumer[Any]:
        consumer = serializer.incremental_deserialize()
        next(consumer)
        return consumer

    @pytest.mark.parametrize(["data", "expected_output"], DESERIALIZE_PARAMS)
    def test____deserialize(self, serializer: CBORSerializer[Any, Any], data: bytes, expected_output: Any) -> None:
        # Arrange

        # Act
        output = serializer.deserialize(data)

        # Assert
        assert type(output) is type(expected_output)
        if isinstance(expected_output, float) and math.isnan(expected_output):
            assert math.isnan(output)
        else:
            assert output == expected_output

    @pytest.mark.parametrize(["data", "expected_output"], INCREMENTAL_DESERIALIZE_PARAMS)
    def test____incremental_deserialize____oneshot_valid_packet(
        self,
        consumer: DeserializerConsumer[Any],
        data: bytes,
        expected_output: Any,
    ) -> None:
        # Arrange

        # Act
        output, remainder = self.deserialize_for_test(consumer, data)

        # Assert
        assert not remainder
        assert type(output) is type(expected_output)
        assert output == expected_output

    @pytest.mark.parametrize(["data", "expected_output"], INCREMENTAL_DESERIALIZE_PARAMS)
    @pytest.mark.parametrize("expected_remainder", list(map(lambda v: v[0], INCREMENTAL_DESERIALIZE_PARAMS)))
    def test____incremental_deserialize____chunk_with_remainder(
        self,
        consumer: DeserializerConsumer[Any],
        data: bytes,
        expected_output: Any,
        expected_remainder: bytes,
    ) -> None:
        # Arrange
        data += expected_remainder

        # Act
        output, remainder = self.deserialize_for_test(consumer, data)

        # Assert
        assert output == expected_output
        assert remainder == expected_remainder

    @pytest.mark.parametrize(["data", "expected_output"], INCREMENTAL_DESERIALIZE_PARAMS)
    def test____incremental_deserialize____handle_partial_document(
        self,
        consumer: DeserializerConsumer[Any],
        data: bytes,
        expected_output: Any,
    ) -> None:
        # Arrange
        import struct

        bytes_sequence: tuple[bytes, ...] = struct.unpack(f"{len(data)}c", data)

        # Act
        for chunk in bytes_sequence[:-1]:
            with pytest.raises(EOFError):
                _ = self.deserialize_for_test(consumer, chunk)
        output, remainder = self.deserialize_for_test(consumer, bytes_sequence[-1])

        # Assert
        assert not remainder
        assert type(output) is type(expected_output)
        assert output == expected_output
