# mypy: disable-error-code=override

from __future__ import annotations

import dataclasses
import json
from typing import Any, final

from easynetwork.serializers.json import JSONEncoderConfig, JSONSerializer

import pytest

from .base import BaseTestIncrementalSerializer, BaseTestSerializerExtraData
from .samples.json import BIG_JSON, SAMPLES

# 'BIG_JSON' serialized is approximatively 7.5KiB long.
TOO_BIG_JSON = BIG_JSON * 2

TOO_BIG_JSON_SERIALIZED = json.dumps(TOO_BIG_JSON, ensure_ascii=False).encode("utf-8")


@final
class TestJSONSerializer(BaseTestIncrementalSerializer, BaseTestSerializerExtraData):
    #### Serializers

    BUFFER_LIMIT = 14 * 1024  # 14KiB

    assert len(TOO_BIG_JSON_SERIALIZED) > BUFFER_LIMIT

    @pytest.fixture(scope="class")
    @staticmethod
    def encoder_config() -> JSONEncoderConfig:
        return JSONEncoderConfig(ensure_ascii=False)

    @pytest.fixture(scope="class", params=[False, True], ids=lambda p: f"use_lines=={p}")
    @staticmethod
    def use_lines(request: Any) -> bool:
        return request.param

    @pytest.fixture(scope="class")
    @classmethod
    def serializer_for_serialization(cls, encoder_config: JSONEncoderConfig, use_lines: bool) -> JSONSerializer:
        return JSONSerializer(encoder_config=encoder_config, use_lines=use_lines, limit=cls.BUFFER_LIMIT)

    @pytest.fixture(scope="class")
    @classmethod
    def serializer_for_deserialization(cls, use_lines: bool) -> JSONSerializer:
        return JSONSerializer(use_lines=use_lines, limit=cls.BUFFER_LIMIT)

    #### Packets to test

    @pytest.fixture(scope="class", params=[pytest.param(p, id=f"packet: {id}") for p, id in SAMPLES])
    @staticmethod
    def packet_to_serialize(request: Any) -> Any:
        return request.param

    #### One-shot Serialize

    @pytest.fixture(scope="class")
    @classmethod
    def expected_complete_data(cls, packet_to_serialize: Any, encoder_config: JSONEncoderConfig) -> bytes:
        return json.dumps(packet_to_serialize, **dataclasses.asdict(encoder_config), separators=(",", ":")).encode("utf-8")

    #### Incremental Serialize

    @pytest.fixture(scope="class")
    @staticmethod
    def expected_joined_data(expected_complete_data: bytes, use_lines: bool) -> bytes:
        if use_lines or not expected_complete_data.startswith((b"{", b"[", b'"')):
            return expected_complete_data + b"\n"
        return expected_complete_data

    #### One-shot Deserialize

    @pytest.fixture(scope="class")
    @staticmethod
    def complete_data(packet_to_serialize: Any, use_lines: bool) -> bytes:
        indent: int | None = None
        if not use_lines:
            # Test with indentation to see whitespace handling
            indent = 4

        return json.dumps(packet_to_serialize, ensure_ascii=False, indent=indent).encode("utf-8")

    #### Incremental Deserialize

    @pytest.fixture(scope="class")
    @staticmethod
    def complete_data_for_incremental_deserialize(complete_data: bytes) -> bytes:
        return complete_data + b"\n"

    #### Invalid data

    @pytest.fixture(scope="class", params=[b"invalid", b"\0", '{"é": 123}'.encode("latin-1")])
    @staticmethod
    def invalid_complete_data(request: Any, use_lines: bool) -> bytes:
        data: bytes = getattr(request, "param")
        if use_lines:
            data += b"\n"
        return data

    @pytest.fixture(
        scope="class",
        params=[
            b"[ invalid ]",
            b"\0",
            '{"é": 123}'.encode("latin-1"),
            pytest.param(TOO_BIG_JSON_SERIALIZED[:-20], id="too_big_json_partial"),
            pytest.param(TOO_BIG_JSON_SERIALIZED + b"\n", id="too_big_json_with_newline"),
            pytest.param(b"4" * (BUFFER_LIMIT + 1024), id="too_big_raw_value_no_newline"),
            pytest.param(b"4" * (BUFFER_LIMIT + 1024) + b"\n", id="too_big_raw_value_with_newline"),
        ],
    )
    @classmethod
    def invalid_partial_data(cls, request: Any, use_lines: bool) -> bytes:
        data: bytes = getattr(request, "param")
        if len(data) <= cls.BUFFER_LIMIT and use_lines:
            data += b"\n"
        return data

    @pytest.fixture(scope="class")
    @classmethod
    def invalid_partial_data_extra_data(cls, invalid_partial_data: bytes, use_lines: bool) -> tuple[bytes, bytes]:
        if len(invalid_partial_data) > cls.BUFFER_LIMIT:
            if invalid_partial_data.endswith(b"\n"):
                if use_lines:
                    return (b"remaining_data", b"remaining_data")
                else:
                    return (b"remaining_data", b"\nremaining_data")
            return (b"remaining_data", b"")
        if invalid_partial_data.startswith(b"\0"):
            return (b"", b"")
        return (b"remaining_data", b"remaining_data")
