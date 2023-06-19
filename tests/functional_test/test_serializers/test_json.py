# -*- coding: utf-8 -*-
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

    @pytest.fixture(scope="class")
    @classmethod
    def serializer_for_serialization(cls) -> JSONSerializer[Any, Any]:
        return JSONSerializer(encoder_config=cls.ENCODER_CONFIG)

    @pytest.fixture(scope="class")
    @staticmethod
    def serializer_for_deserialization() -> JSONSerializer[Any, Any]:
        return JSONSerializer()

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

        return json.dumps(packet_to_serialize, **dataclasses.asdict(cls.ENCODER_CONFIG)).encode("utf-8")

    #### Incremental Serialize

    @pytest.fixture(scope="class")
    @staticmethod
    def expected_joined_data(expected_complete_data: bytes) -> bytes:
        return expected_complete_data + b"\n"

    #### One-shot Deserialize

    @pytest.fixture(scope="class")
    @staticmethod
    def complete_data(packet_to_serialize: Any) -> bytes:
        import json

        # Test with indentation to see whitespace handling
        return json.dumps(packet_to_serialize, ensure_ascii=False, indent=2).encode("utf-8")

    #### Incremental Deserialize

    @pytest.fixture(scope="class")
    @staticmethod
    def complete_data_for_incremental_deserialize(complete_data: bytes) -> bytes:
        return complete_data + b"\n"

    #### Invalid data

    @pytest.fixture(scope="class", params=[b"invalid", b"\0"])
    @staticmethod
    def invalid_complete_data(request: Any) -> bytes:
        return getattr(request, "param")

    @pytest.fixture(scope="class", params=[b"[ invalid ]", b"\0"])
    @staticmethod
    def invalid_partial_data(request: Any) -> bytes:
        return getattr(request, "param")

    @pytest.fixture
    @staticmethod
    def invalid_partial_data_extra_data(invalid_partial_data: bytes) -> bytes:
        if invalid_partial_data == b"\0":
            return b""
        return b"remaining_data"
