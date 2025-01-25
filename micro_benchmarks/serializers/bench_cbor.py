# mypy: disable-error-code=no-any-unimported

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, Any

from easynetwork.serializers.cbor import CBORSerializer

import pytest

from .groups import SerializerGroup

if TYPE_CHECKING:
    from pytest_benchmark.fixture import BenchmarkFixture


@pytest.mark.benchmark(group=SerializerGroup.JSON_SERIALIZE)
def bench_CBORSerializer_serialize(
    benchmark: BenchmarkFixture,
    json_object: Any,
) -> None:
    serializer = CBORSerializer()

    benchmark(serializer.serialize, json_object)


@pytest.mark.benchmark(group=SerializerGroup.JSON_DESERIALIZE)
def bench_CBORSerializer_deserialize(
    benchmark: BenchmarkFixture,
    json_object: Any,
    cbor_data: bytes,
) -> None:
    serializer = CBORSerializer()

    result = benchmark(serializer.deserialize, cbor_data)

    assert result == json_object


@pytest.mark.benchmark(group=SerializerGroup.JSON_INCREMENTAL_SERIALIZE)
def bench_CBORSerializer_incremental_serialize(
    benchmark: BenchmarkFixture,
    json_object: Any,
) -> None:
    serializer = CBORSerializer()

    benchmark(lambda: deque(serializer.incremental_serialize(json_object)))


@pytest.mark.benchmark(group=SerializerGroup.JSON_INCREMENTAL_DESERIALIZE)
@pytest.mark.parametrize("buffered", [False, True], ids=lambda p: f"buffered=={p}")
def bench_CBORSerializer_incremental_deserialize(
    buffered: bool,
    benchmark: BenchmarkFixture,
    cbor_data: bytes,
    json_object: Any,
) -> None:
    serializer = CBORSerializer()

    if buffered:
        nbytes = len(cbor_data)
        buffer: memoryview = serializer.create_deserializer_buffer(nbytes)
        buffer[:nbytes] = cbor_data

        def deserialize() -> Any:
            consumer = serializer.buffered_incremental_deserialize(buffer)
            next(consumer)
            try:
                consumer.send(nbytes)
            except StopIteration as exc:
                return exc.value
            else:
                raise RuntimeError("consumer yielded")

    else:

        def deserialize() -> Any:
            consumer = serializer.incremental_deserialize()
            next(consumer)
            try:
                consumer.send(cbor_data)
            except StopIteration as exc:
                return exc.value
            else:
                raise RuntimeError("consumer yielded")

    result, _ = benchmark(deserialize)

    assert result == json_object
