# -*- coding: Utf-8 -*-

from __future__ import annotations

from functools import cache
from typing import Any, final

from easynetwork.serializers.json import JSONEncoderConfig, JSONSerializer

import pytest

from .base import BaseTestIncrementalSerializer
from .samples.json import JSON_SAMPLES


@final
class TestJSONSerializer(BaseTestIncrementalSerializer):
    ENCODER_CONFIG = JSONEncoderConfig(ensure_ascii=False)

    @pytest.fixture(scope="class")
    @classmethod
    def serializer(cls) -> JSONSerializer[Any, Any]:
        return JSONSerializer(encoder_config=cls.ENCODER_CONFIG)

    @classmethod
    @cache
    def get_oneshot_serialize_sample(cls) -> list[tuple[Any, bytes, str]]:
        import json
        from dataclasses import asdict

        return [(p, json.dumps(p, **asdict(cls.ENCODER_CONFIG)).encode("utf-8"), id) for p, id in JSON_SAMPLES]

    @classmethod
    @cache
    def get_incremental_serialize_sample(cls) -> list[tuple[Any, bytes, str]]:
        return [(p, s + b"\n", id) for p, s, id in cls.get_oneshot_serialize_sample()]

    @classmethod
    @cache
    def get_possible_remaining_data(cls) -> list[tuple[bytes, str]]:
        import base64
        import os

        return [(base64.b64encode(os.urandom(i)), f"remaining_data{i}") for i in range(1, 10)]
