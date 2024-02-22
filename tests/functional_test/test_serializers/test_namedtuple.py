# mypy: disable_error_code=override

from __future__ import annotations

import struct
from typing import Any, NamedTuple, final

from easynetwork.serializers.struct import NamedTupleStructSerializer

import pytest

from .base import BaseTestBufferedIncrementalSerializer, BaseTestSerializerExtraData


class Point(NamedTuple):
    name: str
    x: int
    y: bytes


POINT_FIELD_FORMATS = {
    "name": "10s",
    "x": "q",
    "y": "c",
}


STRUCT_FORMAT = f"!{''.join(map(POINT_FIELD_FORMATS.__getitem__, Point._fields))}"


def pack_point(p: Point, *, encoding: str = "utf-8") -> bytes:
    return struct.pack(STRUCT_FORMAT, p.name.encode(encoding), p.x, p.y)


@final
class TestNamedTupleStructSerializer(BaseTestBufferedIncrementalSerializer, BaseTestSerializerExtraData):
    #### Serializers

    @pytest.fixture(scope="class")
    @classmethod
    def serializer(cls) -> NamedTupleStructSerializer[Point]:
        return NamedTupleStructSerializer(Point, POINT_FIELD_FORMATS)

    @pytest.fixture(scope="class")
    @staticmethod
    def serializer_for_serialization(serializer: NamedTupleStructSerializer[Point]) -> NamedTupleStructSerializer[Point]:
        return serializer

    @pytest.fixture(scope="class")
    @staticmethod
    def serializer_for_deserialization(serializer: NamedTupleStructSerializer[Point]) -> NamedTupleStructSerializer[Point]:
        return serializer

    #### Packets to test

    @pytest.fixture(
        scope="class",
        params=[
            pytest.param(p, id=f"packet: {p!r}")
            for p in [
                Point("", 0, b"\0"),
                Point("string", -4, b"y"),
            ]
        ],
    )
    @staticmethod
    def packet_to_serialize(request: Any) -> Any:
        return request.param

    #### One-shot Serialize

    @pytest.fixture(scope="class")
    @classmethod
    def expected_complete_data(cls, packet_to_serialize: Point) -> bytes:
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

    @pytest.fixture(scope="class", params=["missing_data", "unicode_error"])
    @staticmethod
    def invalid_complete_data(request: pytest.FixtureRequest) -> bytes:
        match request.param:
            case "missing_data":
                return pack_point(Point("string", -4, b"y"))[:-3]
            case "unicode_error":
                return pack_point(Point("é", -4, b"y"), encoding="latin-1")
            case _:
                pytest.fail("Invalid parameter")

    @pytest.fixture(scope="class")
    @staticmethod
    def invalid_partial_data() -> bytes:
        return pack_point(Point("é", -4, b"y"), encoding="latin-1")
