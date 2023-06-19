# -*- coding: utf-8 -*-
# mypy: disable_error_code=override

from __future__ import annotations

from typing import Literal, final

from easynetwork.serializers.line import StringLineSerializer

import pytest

from .base import BaseTestIncrementalSerializer

_NEWLINES: dict[str, bytes] = {
    "LF": b"\n",
    "CR": b"\r",
    "CRLF": b"\r\n",
}


@final
class TestStringLineSerializer(BaseTestIncrementalSerializer):
    #### Serializers
    @pytest.fixture(scope="class", params=list(_NEWLINES))
    @staticmethod
    def newline(request: pytest.FixtureRequest) -> Literal["LF", "CR", "CRLF"]:
        return getattr(request, "param")

    @pytest.fixture(scope="class", params=["ascii", "utf-8"])
    @staticmethod
    def encoding(request: pytest.FixtureRequest) -> str:
        return getattr(request, "param")

    @pytest.fixture(scope="class")
    @staticmethod
    def serializer(newline: Literal["LF", "CR", "CRLF"], encoding: str) -> StringLineSerializer:
        return StringLineSerializer(newline, encoding=encoding)

    @pytest.fixture(scope="class")
    @staticmethod
    def serializer_for_serialization(serializer: StringLineSerializer) -> StringLineSerializer:
        return serializer

    @pytest.fixture(scope="class")
    @staticmethod
    def serializer_for_deserialization(serializer: StringLineSerializer) -> StringLineSerializer:
        return serializer

    #### Packets to test

    @pytest.fixture(scope="class")
    @staticmethod
    def packet_to_serialize(encoding: str) -> str:
        if encoding == "utf-8":
            return "simple line with unicode 'é'"
        return "simple line"

    #### One-shot Serialize

    @pytest.fixture(scope="class")
    @classmethod
    def expected_complete_data(cls, packet_to_serialize: str, encoding: str) -> bytes:
        return packet_to_serialize.encode(encoding)

    #### Incremental Serialize

    @pytest.fixture(scope="class")
    @staticmethod
    def expected_joined_data(expected_complete_data: bytes, newline: Literal["CR", "LF", "CRLF"]) -> bytes:
        return expected_complete_data + _NEWLINES[newline]

    #### One-shot Deserialize

    @pytest.fixture(scope="class")
    @staticmethod
    def complete_data(expected_complete_data: bytes) -> bytes:
        return expected_complete_data

    #### Incremental Deserialize

    @pytest.fixture(scope="class")
    @staticmethod
    def complete_data_for_incremental_deserialize(complete_data: bytes, newline: Literal["CR", "LF", "CRLF"]) -> bytes:
        return complete_data + _NEWLINES[newline]

    #### Invalid data

    @pytest.fixture(scope="class", params=["unicode-error", "newline-error", "empty-string"])
    @staticmethod
    def invalid_complete_data(request: pytest.FixtureRequest, newline: Literal["CR", "LF", "CRLF"]) -> bytes:
        match getattr(request, "param"):
            case "unicode-error":
                return "é".encode("latin-1")
            case "newline-error":
                return b"string with " + _NEWLINES[newline] + b" in it"
            case "empty-string":
                return b""
            case _:
                pytest.fail("Invalid fixture parameter")

    @pytest.fixture
    @staticmethod
    def invalid_partial_data() -> bytes:
        pytest.skip("Cannot be tested")

    #### Other

    @pytest.fixture(scope="class")
    @staticmethod
    def oneshot_extra_data() -> bytes:
        pytest.skip("Does not recognize extra data")
