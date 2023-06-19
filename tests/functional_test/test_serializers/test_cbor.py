# -*- coding: utf-8 -*-
# mypy: disable_error_code=override

from __future__ import annotations

import dataclasses
from typing import Any, final

from easynetwork.serializers.cbor import CBOREncoderConfig, CBORSerializer

import pytest

from .base import BaseTestIncrementalSerializer
from .samples.json import SAMPLES


@final
@pytest.mark.feature_cbor
class TestCBORSerializer(BaseTestIncrementalSerializer):
    #### Serializers

    ENCODER_CONFIG = CBOREncoderConfig()

    @pytest.fixture(scope="class")
    @classmethod
    def serializer_for_serialization(cls) -> CBORSerializer[Any, Any]:
        return CBORSerializer(encoder_config=cls.ENCODER_CONFIG)

    @pytest.fixture(scope="class")
    @staticmethod
    def serializer_for_deserialization() -> CBORSerializer[Any, Any]:
        return CBORSerializer()

    #### Packets to test

    @pytest.fixture(scope="class", params=[pytest.param(p, id=f"packet: {id}") for p, id in SAMPLES])
    @staticmethod
    def packet_to_serialize(request: Any) -> Any:
        return request.param

    #### One-shot Serialize

    @pytest.fixture(scope="class")
    @classmethod
    def expected_complete_data(cls, packet_to_serialize: Any) -> bytes:
        import cbor2

        return cbor2.dumps(packet_to_serialize, **dataclasses.asdict(cls.ENCODER_CONFIG))

    #### Incremental Serialize

    @pytest.fixture(scope="class")
    @staticmethod
    def expected_joined_data(expected_complete_data: bytes) -> bytes:
        return expected_complete_data

    #### One-shot Deserialize

    @pytest.fixture(scope="class")
    @staticmethod
    def complete_data(packet_to_serialize: Any) -> bytes:
        import cbor2

        return cbor2.dumps(packet_to_serialize)

    #### Incremental Deserialize

    @pytest.fixture(scope="class")
    @staticmethod
    def complete_data_for_incremental_deserialize(complete_data: bytes) -> bytes:
        return complete_data

    #### Invalid data

    @pytest.fixture(scope="class")
    @staticmethod
    def invalid_complete_data(complete_data: bytes) -> bytes:
        return complete_data[:-1]  # Missing data error

    @pytest.fixture
    @staticmethod
    def invalid_partial_data() -> bytes:
        pytest.skip("Cannot be tested")
