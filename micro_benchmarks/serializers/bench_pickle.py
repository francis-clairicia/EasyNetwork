# mypy: disable-error-code=no-any-unimported

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from easynetwork.serializers.pickle import PickleSerializer

import pytest

from .groups import SerializerGroup

if TYPE_CHECKING:
    from pytest_benchmark.fixture import BenchmarkFixture


@pytest.mark.benchmark(group=SerializerGroup.PICKLE_SERIALIZE)
@pytest.mark.parametrize("pickler_optimize", [False, True], ids=lambda p: f"pickler_optimize=={p}")
def bench_PickleSerializer_serialize(
    pickler_optimize: bool,
    benchmark: BenchmarkFixture,
    json_object: Any,
) -> None:
    serializer = PickleSerializer(pickler_optimize=pickler_optimize)

    benchmark(serializer.serialize, json_object)


@pytest.mark.benchmark(group=SerializerGroup.PICKLE_DESERIALIZE)
def bench_PickleSerializer_deserialize(
    benchmark: BenchmarkFixture,
    json_object: Any,
    pickle_data: bytes,
) -> None:
    serializer = PickleSerializer()

    result = benchmark(serializer.deserialize, pickle_data)

    assert result == json_object
