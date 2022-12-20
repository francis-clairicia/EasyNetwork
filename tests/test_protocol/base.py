# -*- coding: Utf-8 -*


from __future__ import annotations

from typing import Generator, TypeAlias, TypeVar

_T_co = TypeVar("_T_co", covariant=True)


DeserializerConsumer: TypeAlias = Generator[None, bytes, tuple[_T_co, bytes]]


class BaseTestStreamPacketIncrementalDeserializer:
    @staticmethod
    def deserialize_for_test(gen: Generator[None, bytes, tuple[_T_co, bytes]], chunk: bytes, /) -> tuple[_T_co, bytes]:
        try:
            gen.send(chunk)
        except StopIteration as exc:
            return exc.value
        raise EOFError
