from __future__ import annotations

import enum


@enum.unique
class SerializerGroup(enum.StrEnum):
    @staticmethod
    def _generate_next_value_(name: str, start: int, count: int, last_values: list[str]) -> str:
        return name.lower().replace("_", "-")

    JSON_SERIALIZE = enum.auto()
    JSON_DESERIALIZE = enum.auto()

    JSON_INCREMENTAL_SERIALIZE = enum.auto()
    JSON_INCREMENTAL_DESERIALIZE = enum.auto()

    LINE_SERIALIZE = enum.auto()
    LINE_DESERIALIZE = enum.auto()

    LINE_INCREMENTAL_SERIALIZE = enum.auto()
    LINE_INCREMENTAL_DESERIALIZE = enum.auto()

    PICKLE_SERIALIZE = enum.auto()
    PICKLE_DESERIALIZE = enum.auto()
