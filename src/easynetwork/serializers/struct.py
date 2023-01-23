# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""struct.Struct-based network packet serializer module"""

from __future__ import annotations

__all__ = ["AbstractStructSerializer", "NamedTupleSerializer"]

import struct as _struct
from abc import abstractmethod
from typing import Any, Iterable, Mapping, NamedTuple, TypeVar, final

from .exceptions import DeserializeError
from .stream.abc import FixedSizePacketSerializer

_ST_contra = TypeVar("_ST_contra", contravariant=True)
_DT_co = TypeVar("_DT_co", covariant=True)


class AbstractStructSerializer(FixedSizePacketSerializer[_ST_contra, _DT_co]):
    __slots__ = ("__s",)

    def __init__(self, format: str) -> None:
        if format[0] not in {"@", "=", "<", ">", "!"}:
            format = f"!{format}"  # network byte order
        struct = _struct.Struct(format)
        super().__init__(struct.size)
        self.__s: _struct.Struct = struct

    @abstractmethod
    def iter_values(self, packet: _ST_contra) -> Iterable[Any]:
        raise NotImplementedError

    @final
    def serialize(self, packet: _ST_contra) -> bytes:
        struct = self.__s
        return struct.pack(*self.iter_values(packet))

    @abstractmethod
    def from_tuple(self, t: tuple[Any, ...]) -> _DT_co:
        raise NotImplementedError

    @final
    def deserialize(self, data: bytes) -> _DT_co:
        struct = self.__s
        try:
            packet_tuple: tuple[Any, ...] = struct.unpack(data)
        except _struct.error as exc:
            raise DeserializeError(f"Invalid value: {exc}") from exc
        try:
            return self.from_tuple(packet_tuple)
        except Exception as exc:
            raise DeserializeError(f"Error when building packet from unpacked struct value: {exc}") from exc

    @property
    @final
    def struct(self) -> _struct.Struct:
        return self.__s


_NT = TypeVar("_NT", bound=NamedTuple)


class NamedTupleSerializer(AbstractStructSerializer[_NT, _NT]):
    __slots__ = ("__namedtuple_cls",)

    def __init__(self, namedtuple_cls: type[_NT], fields_format: Mapping[str, str], format_endianness: str = "") -> None:
        if not NamedTupleSerializer.is_namedtuple_class(namedtuple_cls):
            raise TypeError("Expected namedtuple class")

        if not format_endianness:
            format_endianness = "!"

        super().__init__(f"{format_endianness}{''.join(map(fields_format.__getitem__, namedtuple_cls._fields))}")
        self.__namedtuple_cls: type[_NT] = namedtuple_cls

    @staticmethod
    def is_namedtuple_class(o: type[Any]) -> bool:
        return (
            issubclass(o, tuple)
            and o is not tuple
            and all(
                callable(getattr(o, callable_attr, None))
                for callable_attr in (
                    "_make",
                    "_asdict",
                    "_replace",
                )
            )
            and isinstance(getattr(o, "_fields", None), tuple)
        )

    @final
    def iter_values(self, packet: _NT) -> _NT:
        assert isinstance(packet, self.__namedtuple_cls)
        return packet

    @final
    def from_tuple(self, t: tuple[Any, ...]) -> _NT:
        return self.__namedtuple_cls._make(t)
