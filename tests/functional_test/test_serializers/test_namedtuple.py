# -*- coding: Utf-8 -*-

from __future__ import annotations

from functools import cache
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


@final
class TestNamedTupleStructSerializer(BaseTestIncrementalSerializer):
    @pytest.fixture(scope="class")
    @classmethod
    def serializer(cls) -> NamedTupleStructSerializer[Point]:
        return NamedTupleStructSerializer(Point, POINT_FIELD_FORMATS)

    @classmethod
    @cache
    def get_oneshot_serialize_sample(cls) -> list[tuple[Any, bytes] | tuple[Any, bytes, str]]:
        import struct

        s = struct.Struct("!10sqc")

        return [
            (p, s.pack(p.name.encode(), p.x, p.y), repr(p))
            for p in [
                Point("", 0, b"\0"),
                Point("string", -4, b"y"),
            ]
        ]

    @classmethod
    @cache
    def get_incremental_serialize_sample(cls) -> list[tuple[Any, bytes] | tuple[Any, bytes, str]]:
        return cls.get_oneshot_serialize_sample()

    @classmethod
    @cache
    def get_possible_remaining_data(cls) -> list[bytes | tuple[bytes, str]]:
        import base64
        import os

        return [(base64.b64encode(os.urandom(i)), f"remaining_data{i}") for i in range(1, 10)]
