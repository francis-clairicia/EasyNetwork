# Copyright 2021-2023, Francis Clairicia-Rose-Claire-Josephine
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
#
"""struct.Struct-based network packet serializer module"""

from __future__ import annotations

__all__ = ["AbstractStructSerializer", "NamedTupleStructSerializer"]

from abc import abstractmethod
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, Generic, NamedTuple, TypeVar, final

from ..exceptions import DeserializeError
from ._typevars import DeserializedPacketT_co, SerializedPacketT_contra
from .base_stream import FixedSizePacketSerializer

if TYPE_CHECKING:
    from struct import Struct as _Struct

    from _typeshed import SupportsKeysAndGetItem


_ENDIANNESS_CHARACTERS: frozenset[str] = frozenset({"@", "=", "<", ">", "!"})


class AbstractStructSerializer(FixedSizePacketSerializer[SerializedPacketT_contra, DeserializedPacketT_co]):
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
    def iter_values(self, packet: SerializedPacketT_contra) -> Iterable[Any]:
        raise NotImplementedError

    @final
    def serialize(self, packet: SerializedPacketT_contra) -> bytes:
        return self.__s.pack(*self.iter_values(packet))

    @abstractmethod
    def from_tuple(self, t: tuple[Any, ...]) -> DeserializedPacketT_co:
        raise NotImplementedError

    @final
    def deserialize(self, data: bytes) -> DeserializedPacketT_co:
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


NamedTupleVar = TypeVar("NamedTupleVar", bound=NamedTuple)


class NamedTupleStructSerializer(AbstractStructSerializer[NamedTupleVar, NamedTupleVar], Generic[NamedTupleVar]):
    __slots__ = ("__namedtuple_cls", "__string_fields", "__encoding", "__unicode_errors", "__strip_trailing_nul")

    def __init__(
        self,
        namedtuple_cls: type[NamedTupleVar],
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
        self.__namedtuple_cls: type[NamedTupleVar] = namedtuple_cls
        self.__string_fields: frozenset[str] = frozenset(string_fields)
        self.__encoding: str | None = encoding
        self.__unicode_errors: str = unicode_errors
        self.__strip_trailing_nul = bool(strip_string_trailing_nul_bytes)

    @final
    def iter_values(self, packet: NamedTupleVar) -> NamedTupleVar:
        if not isinstance(packet, self.__namedtuple_cls):
            namedtuple_name = self.__namedtuple_cls.__name__
            raise TypeError(f"Expected a {namedtuple_name} instance, got {packet!r}")
        if (encoding := self.__encoding) is not None and self.__string_fields:
            string_fields: dict[str, str] = {field: getattr(packet, field) for field in self.__string_fields}
            unicode_errors: str = self.__unicode_errors
            packet = packet._replace(**{field: value.encode(encoding, unicode_errors) for field, value in string_fields.items()})
        return packet

    @final
    def from_tuple(self, t: tuple[Any, ...]) -> NamedTupleVar:
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
