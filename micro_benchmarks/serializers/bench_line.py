# mypy: disable-error-code=no-any-unimported

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from easynetwork.serializers.line import StringLineSerializer

import pytest

if TYPE_CHECKING:
    from pytest_benchmark.fixture import BenchmarkFixture


@pytest.fixture(scope="module", params=[1, 10], ids=lambda p: f"size=={p}kb")
def line_str(request: pytest.FixtureRequest) -> str:
    size: int = request.param * 1024
    return ("x" * (size - 1)) + "\n"


@pytest.fixture
def line_bytes(line_str: str) -> bytes:
    return bytes(line_str, "utf-8")


def bench_StringLineSerializer_serialize(
    benchmark: BenchmarkFixture,
    line_str: str,
    line_bytes: bytes,
) -> None:
    serializer = StringLineSerializer()

    result = benchmark(serializer.serialize, line_str)

    assert result == line_bytes


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


def bench_StringLineSerializer_incremental_serialize(
    benchmark: BenchmarkFixture,
    line_str: str,
    line_bytes: bytes,
) -> None:
    serializer = StringLineSerializer()

    result = benchmark(lambda: b"".join(serializer.incremental_serialize(line_str)))

    assert result == line_bytes


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

        def deserialize() -> Any:
            consumer = serializer.buffered_incremental_deserialize(buffer)
            start_index: int = next(consumer)
            buffer[start_index : start_index + nbytes] = line_bytes
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
