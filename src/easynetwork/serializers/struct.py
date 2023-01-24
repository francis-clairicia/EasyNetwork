# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""struct.Struct-based network packet serializer module"""

from __future__ import annotations

__all__ = ["AbstractStructSerializer", "NamedTupleStructSerializer"]

import struct as _struct
from abc import abstractmethod
from typing import TYPE_CHECKING, Any, Iterable, NamedTuple, TypeVar, final

from .exceptions import DeserializeError
from .stream.abc import FixedSizePacketSerializer

if TYPE_CHECKING:
    from _typeshed import SupportsKeysAndGetItem

_ST_contra = TypeVar("_ST_contra", contravariant=True)
_DT_co = TypeVar("_DT_co", covariant=True)


_ENDIANNESS_CHARACTERS: frozenset[str] = frozenset({"@", "=", "<", ">", "!"})


class AbstractStructSerializer(FixedSizePacketSerializer[_ST_contra, _DT_co]):
    __slots__ = ("__s",)

    def __init__(self, format: str) -> None:
        if format and format[0] not in _ENDIANNESS_CHARACTERS:
            format = f"!{format}"  # network byte order
        struct = _struct.Struct(format)
        super().__init__(struct.size)
        self.__s: _struct.Struct = struct

    @abstractmethod
    def iter_values(self, packet: _ST_contra) -> Iterable[Any]:
        raise NotImplementedError

    @final
    def serialize(self, packet: _ST_contra) -> bytes:
        return self.__s.pack(*self.iter_values(packet))

    @abstractmethod
    def from_tuple(self, t: tuple[Any, ...]) -> _DT_co:
        raise NotImplementedError

    @final
    def deserialize(self, data: bytes) -> _DT_co:
        try:
            packet_tuple: tuple[Any, ...] = self.__s.unpack(data)
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


class NamedTupleStructSerializer(AbstractStructSerializer[_NT, _NT]):
    __slots__ = ("__namedtuple_cls",)

    def __init__(
        self,
        namedtuple_cls: type[_NT],
        field_formats: SupportsKeysAndGetItem[str, str],
        format_endianness: str = "",
    ) -> None:
        for field in field_formats.keys():
            if any(c in _ENDIANNESS_CHARACTERS for c in field_formats[field]):
                raise ValueError(f"{field!r}: Invalid field format")

        super().__init__(f"{format_endianness}{''.join(map(field_formats.__getitem__, namedtuple_cls._fields))}")
        self.__namedtuple_cls: type[_NT] = namedtuple_cls

    @final
    def iter_values(self, packet: _NT) -> _NT:
        assert isinstance(packet, self.__namedtuple_cls)
        return packet

    @final
    def from_tuple(self, t: tuple[Any, ...]) -> _NT:
        return self.__namedtuple_cls._make(t)
