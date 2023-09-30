# mypy: disable-error-code=override

from __future__ import annotations

import dataclasses
from typing import Any, final

from easynetwork.serializers.json import JSONEncoderConfig, JSONSerializer

import pytest

from .base import BaseTestIncrementalSerializer
from .samples.json import SAMPLES


@final
class TestJSONSerializer(BaseTestIncrementalSerializer):
    #### Serializers

    ENCODER_CONFIG = JSONEncoderConfig(ensure_ascii=False)

    @pytest.fixture(scope="class", params=[False, True], ids=lambda p: f"use_lines=={p}")
    @staticmethod
    def use_lines(request: Any) -> bool:
        return request.param

    @pytest.fixture(scope="class")
    @classmethod
    def serializer_for_serialization(cls, use_lines: bool) -> JSONSerializer:
        return JSONSerializer(encoder_config=cls.ENCODER_CONFIG, use_lines=use_lines)

    @pytest.fixture(scope="class")
    @staticmethod
    def serializer_for_deserialization(use_lines: bool) -> JSONSerializer:
        return JSONSerializer(use_lines=use_lines)

    #### Packets to test

    @pytest.fixture(scope="class", params=[pytest.param(p, id=f"packet: {id}") for p, id in SAMPLES])
    @staticmethod
    def packet_to_serialize(request: Any) -> Any:
        return request.param

    #### One-shot Serialize

    @pytest.fixture(scope="class")
    @classmethod
    def expected_complete_data(cls, packet_to_serialize: Any) -> bytes:
        import json

        return json.dumps(packet_to_serialize, **dataclasses.asdict(cls.ENCODER_CONFIG), separators=(",", ":")).encode("utf-8")

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
        import json

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

    @pytest.fixture(scope="class", params=[b"invalid", b"\0"])
    @staticmethod
    def invalid_complete_data(request: Any, use_lines: bool) -> bytes:
        data: bytes = getattr(request, "param")
        if use_lines:
            data += b"\n"
        return data

    @pytest.fixture(scope="class", params=[b"[ invalid ]", b"\0"])
    @staticmethod
    def invalid_partial_data(request: Any, use_lines: bool) -> bytes:
        data: bytes = getattr(request, "param")
        if use_lines:
            data += b"\n"
        return data

    @pytest.fixture
    @staticmethod
    def invalid_partial_data_extra_data(invalid_partial_data: bytes) -> bytes:
        if invalid_partial_data.startswith(b"\0"):
            return b""
        return b"remaining_data"
