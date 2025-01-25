# mypy: disable-error-code=no-any-unimported

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, Any

from easynetwork.serializers.line import StringLineSerializer

import pytest

from ..conftest import PAYLOAD_SIZE_LEVEL
from .groups import SerializerGroup

if TYPE_CHECKING:
    from pytest_benchmark.fixture import BenchmarkFixture


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "line_str" in metafunc.fixturenames:
        metafunc.parametrize(
            "line_str",
            list(metafunc.config.getoption(PAYLOAD_SIZE_LEVEL)),
            indirect=True,
            ids=lambda p: f"size=={p}kb",
        )


@pytest.fixture(scope="module")
def line_str(request: pytest.FixtureRequest) -> str:
    size: int = request.param * 1024
    return ("x" * (size - 1)) + "\n"


@pytest.fixture(scope="module")
def line_bytes(line_str: str) -> bytes:
    return bytes(line_str, "utf-8")


@pytest.mark.benchmark(group=SerializerGroup.LINE_SERIALIZE)
def bench_StringLineSerializer_serialize(
    benchmark: BenchmarkFixture,
    line_str: str,
    line_bytes: bytes,
) -> None:
    serializer = StringLineSerializer()

    result = benchmark(serializer.serialize, line_str)

    assert result == line_bytes


@pytest.mark.benchmark(group=SerializerGroup.LINE_DESERIALIZE)
@pytest.mark.parametrize("keep_end", [False, True], ids=lambda p: f"keep_end=={p}")
def bench_StringLineSerializer_deserialize(
    keep_end: bool,
    benchmark: BenchmarkFixture,
    line_str: str,
    line_bytes: bytes,
) -> None:
    serializer = StringLineSerializer(keep_end=keep_end)

    result = benchmark(serializer.deserialize, line_bytes)

    if keep_end:
        assert result == line_str
    else:
        assert result == line_str.removesuffix("\n")


@pytest.mark.benchmark(group=SerializerGroup.LINE_INCREMENTAL_SERIALIZE)
def bench_StringLineSerializer_incremental_serialize(
    benchmark: BenchmarkFixture,
    line_str: str,
    line_bytes: bytes,
) -> None:
    serializer = StringLineSerializer()

    result = b"".join(benchmark(lambda: deque(serializer.incremental_serialize(line_str))))

    assert result == line_bytes


@pytest.mark.benchmark(group=SerializerGroup.LINE_INCREMENTAL_DESERIALIZE)
@pytest.mark.parametrize("keep_end", [False, True], ids=lambda p: f"keep_end=={p}")
@pytest.mark.parametrize("buffered", [False, True], ids=lambda p: f"buffered=={p}")
def bench_StringLineSerializer_incremental_deserialize(
    keep_end: bool,
    buffered: bool,
    benchmark: BenchmarkFixture,
    line_str: str,
    line_bytes: bytes,
) -> None:
    serializer = StringLineSerializer(keep_end=keep_end)

    if buffered:
        nbytes = len(line_bytes)
        buffer: bytearray = serializer.create_deserializer_buffer(nbytes)
        buffer[:nbytes] = line_bytes

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
                consumer.send(line_bytes)
            except StopIteration as exc:
                return exc.value
            else:
                raise RuntimeError("consumer yielded")

    result, _ = benchmark(deserialize)

    if keep_end:
        assert result == line_str
    else:
        assert result == line_str.removesuffix("\n")
