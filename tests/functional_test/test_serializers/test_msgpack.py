# -*- coding: utf-8 -*-
# mypy: disable_error_code=override

from __future__ import annotations

import dataclasses
from typing import Any, final

from easynetwork.serializers.msgpack import MessagePackerConfig, MessagePackSerializer

import pytest

from .base import BaseTestSerializer
from .samples.json import SAMPLES


@final
@pytest.mark.feature_msgpack
class TestMessagePackSerializer(BaseTestSerializer):
    #### Serializers

    @pytest.fixture(scope="class")
    @staticmethod
    def packer_config() -> MessagePackerConfig:
        return MessagePackerConfig()

    @pytest.fixture(scope="class")
    @staticmethod
    def serializer_for_serialization(packer_config: MessagePackerConfig) -> MessagePackSerializer[Any, Any]:
        return MessagePackSerializer(packer_config=packer_config)

    @pytest.fixture(scope="class")
    @staticmethod
    def serializer_for_deserialization() -> MessagePackSerializer[Any, Any]:
        return MessagePackSerializer()

    #### Packets to test

    @pytest.fixture(scope="class", params=[pytest.param(p, id=f"packet: {id}") for p, id in SAMPLES])
    @staticmethod
    def packet_to_serialize(request: Any) -> Any:
        return request.param

    #### One-shot Serialize

    @pytest.fixture(scope="class")
    @classmethod
    def expected_complete_data(cls, packet_to_serialize: Any, packer_config: MessagePackerConfig) -> bytes:
        import msgpack

        return msgpack.packb(packet_to_serialize, **dataclasses.asdict(packer_config), autoreset=True)

    #### One-shot Deserialize

    @pytest.fixture(scope="class")
    @staticmethod
    def complete_data(packet_to_serialize: Any) -> bytes:
        import msgpack

        return msgpack.packb(packet_to_serialize)

    #### Invalid data

    @pytest.fixture(scope="class")
    @staticmethod
    def invalid_complete_data(complete_data: bytes) -> bytes:
        return complete_data[:-1]  # Missing data error
