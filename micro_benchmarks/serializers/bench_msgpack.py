# mypy: disable-error-code=no-any-unimported

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from easynetwork.serializers.msgpack import MessagePackSerializer

if TYPE_CHECKING:
    from pytest_benchmark.fixture import BenchmarkFixture


def bench_MessagePackSerializer_serialize(
    benchmark: BenchmarkFixture,
    json_object: Any,
) -> None:
    serializer = MessagePackSerializer()

    benchmark(serializer.serialize, json_object)


def bench_MessagePackSerializer_deserialize(
    benchmark: BenchmarkFixture,
    json_object: Any,
    msgpack_data: bytes,
) -> None:
    serializer = MessagePackSerializer()

    result = benchmark(serializer.deserialize, msgpack_data)

    assert result == json_object
