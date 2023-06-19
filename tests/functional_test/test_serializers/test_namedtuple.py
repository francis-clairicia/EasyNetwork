# -*- coding: utf-8 -*-
# mypy: disable_error_code=override

from __future__ import annotations

from typing import Any, NamedTuple, final

from easynetwork.serializers.struct import NamedTupleStructSerializer

import pytest

from .base import BaseTestIncrementalSerializer


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


@final
class TestNamedTupleStructSerializer(BaseTestIncrementalSerializer):
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
        import struct

        return struct.pack(STRUCT_FORMAT, packet_to_serialize.name.encode(), packet_to_serialize.x, packet_to_serialize.y)

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

    @pytest.fixture(scope="class")
    @staticmethod
    def invalid_complete_data(complete_data: bytes) -> bytes:
        return complete_data[:-1]  # Missing data

    @pytest.fixture
    @staticmethod
    def invalid_partial_data() -> bytes:
        pytest.skip("Cannot be tested")
