# mypy: disable_error_code=override

from __future__ import annotations

import random
from typing import Any, final

from easynetwork.serializers.wrapper.compressor import BZ2CompressorSerializer, ZlibCompressorSerializer

import pytest

from .base import BaseTestBufferedIncrementalSerializer, BaseTestSerializerExtraData, NoSerialization

SAMPLES = [
    (b"", "empty bytes"),
    (b"a", "one ascii byte"),
    (b"\xcc", "one unicode byte"),
    (b"z" * 255, "255 unique byte"),
]


def _make_data_invalid(token: bytes) -> bytes:
    return token[:-2] + random.randbytes(5) + token[-2:]


class BaseTestCompressorSerializer(BaseTestBufferedIncrementalSerializer, BaseTestSerializerExtraData):
    #### Serializers: To be defined in subclass

    #### Packets to test

    @pytest.fixture(scope="class", params=[pytest.param(p, id=f"packet: {id}") for p, id in SAMPLES])
    @staticmethod
    def packet_to_serialize(request: Any) -> Any:
        return request.param

    #### One-shot Serialize: To be defined in subclass

    #### Incremental Serialize

    @pytest.fixture(scope="class")
    @staticmethod
    def expected_joined_data(expected_complete_data: bytes) -> bytes:
        return expected_complete_data

    #### One-shot Deserialize: To be defined in subclass

    #### Incremental Deserialize

    @pytest.fixture(scope="class")
    @staticmethod
    def complete_data_for_incremental_deserialize(complete_data: bytes) -> bytes:
        return complete_data

    #### Invalid data

    @pytest.fixture(scope="class")
    @staticmethod
    def invalid_complete_data(complete_data: bytes) -> bytes:
        return _make_data_invalid(complete_data)

    @pytest.fixture(scope="class")
    @staticmethod
    def invalid_partial_data(invalid_complete_data: bytes) -> bytes:
        return invalid_complete_data

    @pytest.fixture(scope="class")
    @staticmethod
    def invalid_partial_data_extra_data() -> tuple[bytes, bytes]:
        return (b"remaining_data", b"")


@final
class TestBZ2CompressorSerializer(BaseTestCompressorSerializer):
    @pytest.fixture(scope="class", params=list(range(1, 10)), ids=lambda level: f"level=={level}")
    @staticmethod
    def compress_level(request: Any) -> Any:
        return request.param

    #### Serializers

    @pytest.fixture(scope="class")
    @staticmethod
    def serializer_for_serialization(compress_level: int) -> BZ2CompressorSerializer[bytes, bytes]:
        return BZ2CompressorSerializer(NoSerialization(), compress_level=compress_level)

    @pytest.fixture(scope="class")
    @staticmethod
    def serializer_for_deserialization() -> BZ2CompressorSerializer[bytes, bytes]:
        return BZ2CompressorSerializer(NoSerialization())

    #### One-shot Serialize

    @pytest.fixture(scope="class")
    @staticmethod
    def expected_complete_data(packet_to_serialize: bytes, compress_level: int) -> bytes:
        import bz2

        return bz2.compress(packet_to_serialize, compress_level)

    #### One-shot Deserialize

    @pytest.fixture(scope="class")
    @staticmethod
    def complete_data(expected_complete_data: bytes) -> bytes:
        return expected_complete_data


@final
class TestZlibCompressorSerializer(BaseTestCompressorSerializer):
    @pytest.fixture(scope="class", params=list(range(1, 10)), ids=lambda level: f"level=={level}")
    @staticmethod
    def compress_level(request: Any) -> Any:
        return request.param

    #### Serializers

    @pytest.fixture(scope="class")
    @staticmethod
    def serializer_for_serialization(compress_level: int) -> ZlibCompressorSerializer[bytes, bytes]:
        return ZlibCompressorSerializer(NoSerialization(), compress_level=compress_level)

    @pytest.fixture(scope="class")
    @staticmethod
    def serializer_for_deserialization() -> ZlibCompressorSerializer[bytes, bytes]:
        return ZlibCompressorSerializer(NoSerialization())

    #### One-shot Serialize

    @pytest.fixture(scope="class")
    @staticmethod
    def expected_complete_data(packet_to_serialize: bytes, compress_level: int) -> bytes:
        import zlib

        return zlib.compress(packet_to_serialize, compress_level)

    #### One-shot Deserialize

    @pytest.fixture(scope="class")
    @staticmethod
    def complete_data(expected_complete_data: bytes) -> bytes:
        return expected_complete_data
