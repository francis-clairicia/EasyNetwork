# mypy: disable_error_code=override

from __future__ import annotations

import struct
from typing import Any, final

from easynetwork.serializers.struct import StructSerializer

import pytest

from .base import BaseTestBufferedIncrementalSerializer, BaseTestSerializerExtraData

STRUCT_FORMAT = "!10sqc"


def pack_point(p: tuple[bytes, int, bytes]) -> bytes:
    return struct.pack(STRUCT_FORMAT, *p)


@final
class TestStructSerializer(BaseTestBufferedIncrementalSerializer, BaseTestSerializerExtraData):
    #### Serializers

    @pytest.fixture(scope="class")
    @classmethod
    def serializer(cls) -> StructSerializer:
        return StructSerializer(STRUCT_FORMAT)

    @pytest.fixture(scope="class")
    @staticmethod
    def serializer_for_serialization(serializer: StructSerializer) -> StructSerializer:
        return serializer

    @pytest.fixture(scope="class")
    @staticmethod
    def serializer_for_deserialization(serializer: StructSerializer) -> StructSerializer:
        return serializer

    #### Packets to test

    @pytest.fixture(
        scope="class",
        params=[
            pytest.param(p, id=f"packet: {p!r}")
            for p in [
                (b"".ljust(10), 0, b"\0"),
                (b"string".ljust(10), -4, b"y"),
            ]
        ],
    )
    @staticmethod
    def packet_to_serialize(request: Any) -> Any:
        return request.param

    #### One-shot Serialize

    @pytest.fixture(scope="class")
    @classmethod
    def expected_complete_data(cls, packet_to_serialize: tuple[bytes, int, bytes]) -> bytes:
        return pack_point(packet_to_serialize)

    #### Incremental Serialize

    @pytest.fixture(scope="class")
    @staticmethod
    def expected_joined_data(expected_complete_data: bytes) -> bytes:
        return expected_complete_data

    #### One-shot Deserialize

    @pytest.fixture(scope="class")
    @staticmethod
    def complete_data(expected_complete_data: bytes) -> bytes:
        return expected_complete_data

    #### Incremental Deserialize

    @pytest.fixture(scope="class")
    @staticmethod
    def complete_data_for_incremental_deserialize(complete_data: bytes) -> bytes:
        return complete_data

    #### Invalid data

    @pytest.fixture(scope="class", params=["missing_data"])
    @staticmethod
    def invalid_complete_data(request: pytest.FixtureRequest) -> bytes:
        match request.param:
            case "missing_data":
                return pack_point((b"string".ljust(10), -4, b"y"))[:-3]
            case _:
                pytest.fail("Invalid parameter")

    @pytest.fixture(scope="class")
    @staticmethod
    def invalid_partial_data() -> bytes:
        pytest.skip("Cannot be tested")
