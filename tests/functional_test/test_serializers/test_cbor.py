# -*- coding: Utf-8 -*-

from __future__ import annotations

from functools import cache
from typing import Any, final

from easynetwork.serializers.cbor import CBOREncoderConfig, CBORSerializer

import pytest

from .base import BaseTestIncrementalSerializer
from .samples.json import JSON_SAMPLES


@final
class TestCBORSerializer(BaseTestIncrementalSerializer):
    ENCODER_CONFIG = CBOREncoderConfig()

    @pytest.fixture(scope="class")
    @classmethod
    def serializer(cls) -> CBORSerializer[Any, Any]:
        return CBORSerializer(encoder_config=cls.ENCODER_CONFIG)

    @classmethod
    @cache
    def get_oneshot_serialize_sample(cls) -> list[tuple[Any, bytes] | tuple[Any, bytes, str]]:
        from dataclasses import asdict

        import cbor2

        return [(p, cbor2.dumps(p, **asdict(cls.ENCODER_CONFIG)), id) for p, id in JSON_SAMPLES]

    @classmethod
    @cache
    def get_incremental_serialize_sample(cls) -> list[tuple[Any, bytes] | tuple[Any, bytes, str]]:
        return cls.get_oneshot_serialize_sample()

    @classmethod
    @cache
    def get_possible_remaining_data(cls) -> list[bytes | tuple[bytes, str]]:
        import os

        return [(os.urandom(i), f"remaining_data{i}") for i in range(1, 10)]
