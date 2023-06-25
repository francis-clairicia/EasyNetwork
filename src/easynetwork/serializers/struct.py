# -*- coding: utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""struct.Struct-based network packet serializer module"""

from __future__ import annotations

__all__ = ["AbstractStructSerializer", "NamedTupleStructSerializer"]

from abc import abstractmethod
from typing import TYPE_CHECKING, Any, Generic, Iterable, NamedTuple, TypeVar, final

from ..exceptions import DeserializeError
from .base_stream import FixedSizePacketSerializer

if TYPE_CHECKING:
    from struct import Struct as _Struct

    from _typeshed import SupportsKeysAndGetItem

_ST_contra = TypeVar("_ST_contra", contravariant=True)
_DT_co = TypeVar("_DT_co", covariant=True)


_ENDIANNESS_CHARACTERS: frozenset[str] = frozenset({"@", "=", "<", ">", "!"})


class AbstractStructSerializer(FixedSizePacketSerializer[_ST_contra, _DT_co]):
    __slots__ = ("__s", "__error_cls")

    def __init__(self, format: str) -> None:
        from struct import Struct, error

        if format and format[0] not in _ENDIANNESS_CHARACTERS:
            format = f"!{format}"  # network byte order
        struct = Struct(format)
        super().__init__(struct.size)
        self.__s: _Struct = struct
        self.__error_cls = error

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
        except self.__error_cls as exc:
            raise DeserializeError(f"Invalid value: {exc}", error_info={"data": data}) from exc
        try:
            return self.from_tuple(packet_tuple)
        except Exception as exc:
            raise DeserializeError(
                f"Error when building packet from unpacked struct value: {exc}",
                error_info={"unpacked_struct": packet_tuple},
            ) from exc

    @property
    @final
    def struct(self) -> _Struct:
        return self.__s


_NT = TypeVar("_NT", bound=NamedTuple)


class NamedTupleStructSerializer(AbstractStructSerializer[_NT, _NT], Generic[_NT]):
    __slots__ = ("__namedtuple_cls", "__string_fields", "__encoding", "__unicode_errors", "__strip_trailing_nul")

    def __init__(
        self,
        namedtuple_cls: type[_NT],
        field_formats: SupportsKeysAndGetItem[str, str],
        format_endianness: str = "",
        encoding: str | None = "utf-8",
        unicode_errors: str = "strict",
        strip_string_trailing_nul_bytes: bool = True,
    ) -> None:
        string_fields: set[str] = set()

        for field in field_formats.keys():
            field_fmt = field_formats[field]
            if any(c in _ENDIANNESS_CHARACTERS for c in field_fmt):
                raise ValueError(f"{field!r}: Invalid field format")
            if field_fmt and field_fmt[-1] == "s":
                if len(field_fmt) > 1 and not field_fmt[:-1].isdecimal():
                    raise ValueError(f"{field!r}: Invalid field format")
                string_fields.add(field)
            elif len(field_fmt) != 1 or not field_fmt.isalpha():
                raise ValueError(f"{field!r}: Invalid field format")
        super().__init__(f"{format_endianness}{''.join(map(field_formats.__getitem__, namedtuple_cls._fields))}")
        self.__namedtuple_cls: type[_NT] = namedtuple_cls
        self.__string_fields: frozenset[str] = frozenset(string_fields)
        self.__encoding: str | None = encoding
        self.__unicode_errors: str = unicode_errors
        self.__strip_trailing_nul = bool(strip_string_trailing_nul_bytes)

    @final
    def iter_values(self, packet: _NT) -> _NT:
        assert isinstance(packet, self.__namedtuple_cls)
        if (encoding := self.__encoding) is not None and self.__string_fields:
            string_fields: dict[str, str] = {field: getattr(packet, field) for field in self.__string_fields}
            unicode_errors: str = self.__unicode_errors
            packet = packet._replace(**{field: value.encode(encoding, unicode_errors) for field, value in string_fields.items()})
        return packet

    @final
    def from_tuple(self, t: tuple[Any, ...]) -> _NT:
        p = self.__namedtuple_cls._make(t)
        string_fields: dict[str, bytes] = {field: getattr(p, field) for field in self.__string_fields}
        if string_fields:
            to_replace: dict[str, Any] | None = None
            if self.__strip_trailing_nul:
                string_fields = {field: value.rstrip(b"\0") for field, value in string_fields.items()}
                to_replace = string_fields
            if (encoding := self.__encoding) is not None:
                unicode_errors: str = self.__unicode_errors
                to_replace = {field: value.decode(encoding, unicode_errors) for field, value in string_fields.items()}
            if to_replace is not None:
                p = p._replace(**to_replace)
        return p
