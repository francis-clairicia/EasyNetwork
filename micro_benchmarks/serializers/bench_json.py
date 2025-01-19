# mypy: disable-error-code=no-any-unimported

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, Any

from easynetwork.serializers.json import JSONSerializer

import pytest

from .groups import SerializerGroup

if TYPE_CHECKING:
    from pytest_benchmark.fixture import BenchmarkFixture


@pytest.mark.benchmark(group=SerializerGroup.JSON_SERIALIZE)
def bench_JSONSerializer_serialize(
    benchmark: BenchmarkFixture,
    json_object: Any,
) -> None:
    serializer = JSONSerializer()

    benchmark(serializer.serialize, json_object)


@pytest.mark.benchmark(group=SerializerGroup.JSON_DESERIALIZE)
def bench_JSONSerializer_deserialize(
    benchmark: BenchmarkFixture,
    json_object: Any,
    json_data: bytes,
) -> None:
    serializer = JSONSerializer()

    result = benchmark(serializer.deserialize, json_data)

    assert result == json_object


@pytest.mark.benchmark(group=SerializerGroup.JSON_INCREMENTAL_SERIALIZE)
@pytest.mark.parametrize("use_lines", [False, True], ids=lambda p: f"use_lines=={p}")
def bench_JSONSerializer_incremental_serialize(
    use_lines: bool,
    benchmark: BenchmarkFixture,
    json_object: Any,
) -> None:
    serializer = JSONSerializer(use_lines=use_lines)

    benchmark(lambda: deque(serializer.incremental_serialize(json_object)))


@pytest.mark.benchmark(group=SerializerGroup.JSON_INCREMENTAL_DESERIALIZE)
@pytest.mark.parametrize("use_lines", [False, True], ids=lambda p: f"use_lines=={p}")
def bench_JSONSerializer_incremental_deserialize(
    use_lines: bool,
    benchmark: BenchmarkFixture,
    json_data: bytes,
    json_object: Any,
) -> None:
    serializer = JSONSerializer(use_lines=use_lines)

    def deserialize() -> Any:
        consumer = serializer.incremental_deserialize()
        next(consumer)
        try:
            consumer.send(json_data)
        except StopIteration as exc:
            return exc.value
        else:
            raise RuntimeError("consumer yielded")

    result, _ = benchmark(deserialize)

    assert result == json_object
