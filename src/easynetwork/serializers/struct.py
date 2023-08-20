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

from .._typevars import _DeserializedPacketT_co, _SerializedPacketT_contra
from ..exceptions import DeserializeError
from .base_stream import FixedSizePacketSerializer

if TYPE_CHECKING:
    import struct as _typing_struct

    from _typeshed import SupportsKeysAndGetItem


_ENDIANNESS_CHARACTERS: frozenset[str] = frozenset({"@", "=", "<", ">", "!"})


class AbstractStructSerializer(FixedSizePacketSerializer[_SerializedPacketT_contra, _DeserializedPacketT_co]):
    r"""
    A base class for structured data.

    To use the serializer directly without additional layers, it is possible to create a subclass with the minimal requirements::

        >>> class StructSerializer(AbstractStructSerializer):
        ...     __slots__ = ()
        ...     def iter_values(self, packet):
        ...         return packet
        ...     def from_tuple(self, t):
        ...         return t
        ...

    And then::

        >>> s = StructSerializer(">ii")
        >>> data = s.serialize((10, 20))
        >>> data
        b'\x00\x00\x00\n\x00\x00\x00\x14'
        >>> s.deserialize(data)
        (10, 20)

    This is an abstract class in order to allow you to include fancy structures like :class:`ctypes.Structure` subclasses.

    See Also:
        The :class:`.NamedTupleStructSerializer` class.
    """

    __slots__ = ("__s", "__error_cls")

    def __init__(self, format: str) -> None:
        """
        Arguments:
            format: The :class:`struct.Struct` format definition string.

        Note:
            If the endianness is not specified, the network byte-order is used::

                >>> s = StructSerializer("qq")  # doctest: +SKIP
                >>> s.struct.format  # doctest: +SKIP
                '!qq'
        """
        from struct import Struct, error

        if format and format[0] not in _ENDIANNESS_CHARACTERS:
            format = f"!{format}"  # network byte order
        struct = Struct(format)
        super().__init__(struct.size)
        self.__s: _typing_struct.Struct = struct
        self.__error_cls = error

    @abstractmethod
    def iter_values(self, packet: _SerializedPacketT_contra, /) -> Iterable[Any]:
        """
        Returns an object suitable for :meth:`struct.Struct.pack`.

        See :meth:`.serialize` for details.

        Arguments:
            packet: The Python object to serialize.

        Returns:
            an iterable object yielding the structure values
        """
        raise NotImplementedError

    @abstractmethod
    def from_tuple(self, t: tuple[Any, ...], /) -> _DeserializedPacketT_co:
        """
        Finishes the packet deserialization by parsing the tuple obtained by :meth:`struct.Struct.unpack`.

        See :meth:`.deserialize` for details.

        Arguments:
            t: A tuple of each elements extracted from the structure.

        Returns:
            the deserialized Python object.
        """
        raise NotImplementedError

    @final
    def serialize(self, packet: _SerializedPacketT_contra) -> bytes:
        """
        Returns the structured data representation of the Python object `packet`.

        Roughly equivalent to::

            def serialize(self, packet):
                to_pack = self.iter_values(packet)
                return self.struct.pack(*to_pack)

        Arguments:
            packet: The Python object to serialize.

        Returns:
            a byte sequence.
        """
        return self.__s.pack(*self.iter_values(packet))

    @final
    def deserialize(self, data: bytes) -> _DeserializedPacketT_co:
        """
        Creates a Python object representing the structure from `data`.

        Roughly equivalent to::

            def deserialize(self, data):
                unpacked_data = self.struct.unpack(data)
                return self.from_tuple(unpacked_data)

        Arguments:
            data: The byte sequence to deserialize.

        Raises:
            DeserializeError: A :class:`struct.error` have been raised.
            DeserializeError: :meth:`from_tuple` crashed.

        Returns:
            the deserialized Python object.
        """
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
    def struct(self) -> _typing_struct.Struct:
        """The underlying :class:`struct.Struct` instance. Read-only attribute."""
        return self.__s


NamedTupleVar = TypeVar("NamedTupleVar", bound=NamedTuple)


class NamedTupleStructSerializer(AbstractStructSerializer[NamedTupleVar, NamedTupleVar], Generic[NamedTupleVar]):
    r"""
    Generic class to handle a :term:`named tuple` with a :class:`struct.Struct` object.

    Accepts classes created directly from :func:`collections.namedtuple` factory::

        >>> import collections
        >>> Point = collections.namedtuple("Point", ("x", "y"))

    ...or declared with :class:`typing.NamedTuple`::

        from typing import NamedTuple

        class Point(NamedTuple):
            x: int
            y: int

    They are used like this::

        >>> s = NamedTupleStructSerializer(Point, {"x": "i", "y": "i"}, format_endianness=">")
        >>> s.struct.format
        '>ii'
        >>> data = s.serialize(Point(x=10, y=20))
        >>> data
        b'\x00\x00\x00\n\x00\x00\x00\x14'
        >>> s.deserialize(data)
        Point(x=10, y=20)
    """

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
        r"""
        Arguments:
            namedtuple_cls: A :term:`named tuple` type.
            field_formats: A mapping of string format for the `namedtuple_cls` fields.
            format_endianness: The endianness character. Defaults to empty string.
            encoding: String fields encoding. Can be disabled by setting it to :data:`None`.
            unicode_errors: Controls how encoding errors are handled. Ignored if `encoding` is set to :data:`None`.
            strip_string_trailing_nul_bytes: If `True` (the default), removes ``\0`` characters at the end of a string field.

        See Also:
            :ref:`standard-encodings` and :ref:`error-handlers`.
        """
        string_fields: set[str] = set()

        if format_endianness:
            if format_endianness not in _ENDIANNESS_CHARACTERS:
                raise ValueError("Invalid endianness character")

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
        """
        Returns the named tuple to pack using :meth:`struct.Struct.pack`.

        In most case, this method will directly return `packet`.

        If there are string fields and `encoding` is a non-:data:`None` value, this method will return a shallow copy of
        the named tuple with the encoded strings.

        Example:
            The named tuple::

                >>> from typing import NamedTuple
                >>> class Person(NamedTuple):
                ...     name: str
                ...     age: int

            In application::

                >>> s = NamedTupleStructSerializer(Person, {"name": "10s", "age": "I"})
                >>> s.iter_values(Person(name="John", age=20))
                Person(name=b'John', age=20)

        Arguments:
            packet: The `namedtuple_cls` instance.

        Returns:
            a `namedtuple_cls` instance.
        """
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
        r"""
        Constructs the named tuple from the given tuple.

        If there are string fields and `encoding` is a non-:data:`None` value, their values will be decoded.

        If `strip_string_trailing_nul_bytes` was set to :data:`True`, the ``"\0"`` characters at the end of the string fields,
        added for padding, will be removed.

        Example:
            The named tuple::

                >>> from typing import NamedTuple
                >>> class Person(NamedTuple):
                ...     name: str
                ...     age: int

            In application::

                >>> s = NamedTupleStructSerializer(Person, {"name": "10s", "age": "I"})
                >>> t = s.struct.unpack(b'John\x00\x00\x00\x00\x00\x00\x00\x00\x00\x14')
                >>> t
                (b'John\x00\x00\x00\x00\x00\x00', 20)
                >>> s.from_tuple(t)
                Person(name='John', age=20)

        Arguments:
            t: A tuple of each elements extracted from the structure.

        Returns:
            a `namedtuple_cls` instance.
        """
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
