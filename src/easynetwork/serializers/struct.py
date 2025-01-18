# Copyright 2021-2025, Francis Clairicia-Rose-Claire-Josephine
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
"""Network packet serializer module based on structures."""

from __future__ import annotations

__all__ = ["AbstractStructSerializer", "NamedTupleStructSerializer", "StructSerializer"]

from abc import abstractmethod
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, NamedTuple, TypeVar, final

from .._typevars import _T_ReceivedDTOPacket, _T_SentDTOPacket
from ..exceptions import DeserializeError
from ..lowlevel import _utils
from .base_stream import FixedSizePacketSerializer

if TYPE_CHECKING:
    from struct import Struct

    from _typeshed import SupportsKeysAndGetItem


_ENDIANNESS_CHARACTERS: frozenset[str] = frozenset({"@", "=", "<", ">", "!"})


class AbstractStructSerializer(FixedSizePacketSerializer[_T_SentDTOPacket, _T_ReceivedDTOPacket]):
    r"""
    A base class for structured data.

    To use the serializer directly without additional layers, it is possible to create a subclass with the minimal requirements::

        >>> class MyStructSerializer(AbstractStructSerializer):
        ...     __slots__ = ()
        ...     def iter_values(self, packet):
        ...         return packet
        ...     def from_tuple(self, packet_tuple):
        ...         return packet_tuple
        ...

    And then::

        >>> s = MyStructSerializer(">ii")
        >>> data = s.serialize((10, 20))
        >>> data
        b'\x00\x00\x00\n\x00\x00\x00\x14'
        >>> s.deserialize(data)
        (10, 20)

    This is an abstract class in order to allow you to include fancy structures like :class:`ctypes.Structure` subclasses.

    Note:
        If the endianness is not specified, the network byte-order is used::

            >>> s = MyStructSerializer("qq")
            >>> s.struct.format
            '!qq'

    See Also:
        :class:`.StructSerializer`
            Default implementation without additional layers.

        :class:`.NamedTupleStructSerializer`
            Specialization for named tuple instances.
    """

    __slots__ = ("__s", "__error_cls")

    def __init__(self, format: str, *, debug: bool = False) -> None:
        """
        Parameters:
            format: The :class:`struct.Struct` format definition string.
            debug: If :data:`True`, add information to :exc:`.DeserializeError` via the ``error_info`` attribute.
        """
        import struct as struct_module

        if format and format[0] not in _ENDIANNESS_CHARACTERS:
            format = f"!{format}"  # network byte order
        struct = struct_module.Struct(format)
        super().__init__(struct.size, debug=debug)
        self.__s: Struct = struct
        self.__error_cls = struct_module.error

    @abstractmethod
    def iter_values(self, packet: _T_SentDTOPacket, /) -> Iterable[Any]:
        """
        Returns an object suitable for :meth:`struct.Struct.pack`.

        See :meth:`serialize` for details.

        Parameters:
            packet: The Python object to serialize.

        Returns:
            an iterable object yielding the structure values
        """
        raise NotImplementedError

    @abstractmethod
    def from_tuple(self, packet_tuple: tuple[Any, ...], /) -> _T_ReceivedDTOPacket:
        """
        Finishes the packet deserialization by parsing the tuple obtained by :meth:`struct.Struct.unpack`.

        See :meth:`deserialize` for details.

        Parameters:
            packet_tuple: A tuple of each elements extracted from the structure.

        Returns:
            the deserialized Python object.
        """
        raise NotImplementedError

    @final
    def serialize(self, packet: _T_SentDTOPacket) -> bytes:
        """
        Returns the structured data representation of the Python object `packet`.

        Roughly equivalent to::

            def serialize(self, packet):
                to_pack = self.iter_values(packet)
                return self.struct.pack(*to_pack)

        Parameters:
            packet: The Python object to serialize.

        Returns:
            a byte sequence.
        """
        return self.__s.pack(*self.iter_values(packet))

    @final
    def deserialize(self, data: bytes) -> _T_ReceivedDTOPacket:
        """
        Creates a Python object representing the structure from `data`.

        Roughly equivalent to::

            def deserialize(self, data):
                unpacked_data = self.struct.unpack(data)
                return self.from_tuple(unpacked_data)

        Parameters:
            data: The byte sequence to deserialize.

        Raises:
            DeserializeError: A :class:`struct.error` have been raised.

        Returns:
            the deserialized Python object.
        """
        try:
            packet_tuple: tuple[Any, ...] = self.__s.unpack(data)
        except self.__error_cls as exc:
            msg = f"Invalid value: {exc}"
            if self.debug:
                raise DeserializeError(msg, error_info={"data": data}) from exc
            raise DeserializeError(msg) from exc
        return self.from_tuple(packet_tuple)

    @property
    @final
    def struct(self) -> Struct:
        """The underlying :class:`struct.Struct` instance. Read-only attribute."""
        return self.__s


class StructSerializer(AbstractStructSerializer[tuple[Any, ...], tuple[Any, ...]]):
    r"""
    Generic class to handle a :class:`tuple` of data with a :class:`struct.Struct` object.

    Example:

        >>> s = StructSerializer(">ii")
        >>> data = s.serialize((10, 20))
        >>> data
        b'\x00\x00\x00\n\x00\x00\x00\x14'
        >>> s.deserialize(data)
        (10, 20)

    Note:
        If the endianness is not specified, the network byte-order is used::

            >>> s = StructSerializer("qq")
            >>> s.struct.format
            '!qq'
    """

    __slots__ = ()

    @final
    @_utils.inherit_doc(AbstractStructSerializer)
    def iter_values(self, packet: tuple[Any, ...], /) -> tuple[Any, ...]:
        if __debug__:
            if not isinstance(packet, tuple):
                raise TypeError(f"Expected a tuple instance, got {packet!r}")
        return packet

    @final
    @_utils.inherit_doc(AbstractStructSerializer)
    def from_tuple(self, packet_tuple: tuple[Any, ...], /) -> tuple[Any, ...]:
        return packet_tuple


_T_NamedTuple = TypeVar("_T_NamedTuple", bound=NamedTuple)


class NamedTupleStructSerializer(AbstractStructSerializer[_T_NamedTuple, _T_NamedTuple]):
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

    Note:
        If the endianness is not specified, the network byte-order is used::

            >>> s = NamedTupleStructSerializer(Point, {"x": "i", "y": "i"})
            >>> s.struct.format
            '!ii'
    """

    __slots__ = ("__namedtuple_cls", "__string_fields", "__encoding", "__unicode_errors", "__strip_trailing_nul")

    def __init__(
        self,
        namedtuple_cls: type[_T_NamedTuple],
        field_formats: SupportsKeysAndGetItem[str, str],
        format_endianness: str = "",
        encoding: str | None = "utf-8",
        unicode_errors: str = "strict",
        strip_string_trailing_nul_bytes: bool = True,
        *,
        debug: bool = False,
    ) -> None:
        r"""
        Parameters:
            namedtuple_cls: A :term:`named tuple` type.
            field_formats: A mapping of string format for the `namedtuple_cls` fields.
            format_endianness: The endianness character. Defaults to empty string.
            encoding: String fields encoding. Can be disabled by setting it to :data:`None`.
            unicode_errors: Controls how encoding errors are handled. Ignored if `encoding` is set to :data:`None`.
            strip_string_trailing_nul_bytes: If `True` (the default), removes ``\0`` characters at the end of a string field.
            debug: If :data:`True`, add information to :exc:`.DeserializeError` via the ``error_info`` attribute.

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
            if field_fmt[-1:] == "s":
                if len(field_fmt) > 1 and not field_fmt[:-1].isdecimal():
                    raise ValueError(f"{field!r}: Invalid field format")
                string_fields.add(field)
            elif len(field_fmt) != 1 or not field_fmt.isalpha():
                raise ValueError(f"{field!r}: Invalid field format")
        super().__init__(f"{format_endianness}{''.join(field_formats[field] for field in namedtuple_cls._fields)}", debug=debug)
        self.__namedtuple_cls: type[_T_NamedTuple] = namedtuple_cls
        self.__string_fields: frozenset[str] = frozenset(string_fields)
        self.__encoding: str | None = encoding
        self.__unicode_errors: str = unicode_errors
        self.__strip_trailing_nul = bool(strip_string_trailing_nul_bytes)

    @final
    def iter_values(self, packet: _T_NamedTuple) -> _T_NamedTuple:
        """
        Returns the named tuple to pack using :meth:`struct.Struct.pack`.

        In most case, this method will directly return `packet`.

        If there are string fields and `encoding` is not :data:`None`, this method will return a shallow copy of
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

        Parameters:
            packet: The `namedtuple_cls` instance.

        Returns:
            a `namedtuple_cls` instance.
        """
        if __debug__:
            if not isinstance(packet, self.__namedtuple_cls):
                namedtuple_name = self.__namedtuple_cls.__name__
                raise TypeError(f"Expected a {namedtuple_name} instance, got {packet!r}")
        if (encoding := self.__encoding) is not None and self.__string_fields:
            string_fields: dict[str, str] = {field: getattr(packet, field) for field in self.__string_fields}
            unicode_errors: str = self.__unicode_errors
            packet = packet._replace(**{field: bytes(value, encoding, unicode_errors) for field, value in string_fields.items()})
        return packet

    @final
    def from_tuple(self, packet_tuple: tuple[Any, ...], /) -> _T_NamedTuple:
        r"""
        Constructs the named tuple from the given tuple.

        If there are string fields and `encoding` is not :data:`None`, their values will be decoded.

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

        Parameters:
            packet_tuple: A tuple of each elements extracted from the structure.

        Returns:
            a `namedtuple_cls` instance.
        """
        p = self.__namedtuple_cls._make(packet_tuple)
        string_fields: dict[str, bytes] = {field: getattr(p, field) for field in self.__string_fields}
        if string_fields:
            to_replace: dict[str, Any] | None = None
            if self.__strip_trailing_nul:
                string_fields = {field: value.rstrip(b"\0") for field, value in string_fields.items()}
                to_replace = string_fields
            if (encoding := self.__encoding) is not None:
                unicode_errors: str = self.__unicode_errors
                try:
                    to_replace = {field: str(value, encoding, unicode_errors) for field, value in string_fields.items()}
                except UnicodeError as exc:
                    msg = f"UnicodeError when building packet from unpacked struct value: {exc}"
                    if self.debug:
                        raise DeserializeError(
                            msg,
                            error_info={"unpacked_struct": packet_tuple},
                        ) from exc
                    raise DeserializeError(msg) from exc
            if to_replace is not None:
                p = p._replace(**to_replace)
        return p
