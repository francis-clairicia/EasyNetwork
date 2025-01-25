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
"""String line packet serializer module."""

from __future__ import annotations

__all__ = ["StringLineSerializer"]

from collections.abc import Generator
from typing import Literal, assert_never, final

from ..exceptions import DeserializeError, IncrementalDeserializeError
from ..lowlevel.constants import DEFAULT_SERIALIZER_LIMIT
from .abc import BufferedIncrementalPacketSerializer
from .base_stream import _buffered_readuntil
from .tools import GeneratorStreamReader


class StringLineSerializer(BufferedIncrementalPacketSerializer[str, str, bytearray]):
    """
    A :term:`serializer` to handle ASCII-based protocols.
    """

    __slots__ = (
        "__separator",
        "__limit",
        "__keep_end",
        "__encoding",
        "__unicode_errors",
        "__debug",
    )

    def __init__(
        self,
        newline: Literal["LF", "CR", "CRLF"] = "LF",
        *,
        encoding: str = "ascii",
        unicode_errors: str = "strict",
        limit: int = DEFAULT_SERIALIZER_LIMIT,
        keep_end: bool = False,
        debug: bool = False,
    ) -> None:
        r"""
        Parameters:
            newline: Magic string indicating the newline character sequence.
                     Possible values are:

                     - ``"LF"`` (the default): Line feed character (``"\n"``).

                     - ``"CR"``: Carriage return character (``"\r"``).

                     - ``"CRLF"``: Carriage return + line feed character sequence (``"\r\n"``).
            encoding: String encoding. Defaults to ``"ascii"``.
            unicode_errors: Controls how encoding errors are handled.
            limit: Maximum buffer size. Used in incremental serialization context.
            keep_end: If :data:`True`, returned data will include the separator at the end.
            debug: If :data:`True`, add information to :exc:`.DeserializeError` via the ``error_info`` attribute.

        See Also:
            :ref:`standard-encodings` and :ref:`error-handlers`.
        """
        separator: bytes
        match newline:
            case "LF":
                separator = b"\n"
            case "CR":
                separator = b"\r"
            case "CRLF":
                separator = b"\r\n"
            case _:
                assert_never(newline)
        if limit <= 0:
            raise ValueError("limit must be a positive integer")
        super().__init__()
        self.__separator: bytes = separator
        self.__limit: int = limit
        self.__keep_end: bool = bool(keep_end)
        self.__encoding: str = encoding
        self.__unicode_errors: str = unicode_errors
        self.__debug: bool = bool(debug)

    @final
    def serialize(self, packet: str) -> bytes:
        """
        Encodes the given string to bytes.

        Roughly equivalent to::

            def serialize(self, packet):
                return packet.encode()

        Example:
            >>> s = StringLineSerializer()
            >>> s.serialize("character string")
            b'character string'

        Parameters:
            packet: The string to encode.

        Raises:
            TypeError: `packet` is not a :class:`str`.
            UnicodeError: Invalid string.

        Returns:
            the byte sequence.

        Important:
            The output **does not** contain `newline`.
        """
        return bytes(packet, self.__encoding, self.__unicode_errors)

    @final
    def incremental_serialize(self, packet: str) -> Generator[bytes]:
        """
        Encodes the given string to bytes and appends `separator`.

        See :meth:`.AbstractIncrementalPacketSerializer.incremental_serialize` documentation for details.

        Raises:
            TypeError: `packet` is not a :class:`str`.
            UnicodeError: Invalid string.
        """
        data = bytes(packet, self.__encoding, self.__unicode_errors)
        if not data:
            return
        separator: bytes = self.__separator
        if not data.endswith(separator):
            data += separator
        yield data

    @final
    def deserialize(self, data: bytes) -> str:
        r"""
        Decodes `data` and returns the string.

        Roughly equivalent to::

            def deserialize(self, data):
                return data.decode()

        Example:
            >>> s = StringLineSerializer()
            >>> s.deserialize(b"character string")
            'character string'

        Parameters:
            packet: The data to decode.

        Raises:
            DeserializeError: :class:`UnicodeError` raised when decoding `data`.

        Returns:
            the string.

        Important:
            By default, trailing `newline` sequences are **removed**. This can be change by setting `keep_end` parameter to
            :data:`True` at initialization.
        """
        if not self.__keep_end:
            separator: bytes = self.separator
            while data.endswith(separator):
                data = data.removesuffix(separator)
        try:
            return str(data, self.__encoding, self.__unicode_errors)
        except UnicodeError as exc:
            msg = str(exc)
            if self.debug:
                raise DeserializeError(msg, error_info={"data": data}) from exc
            raise DeserializeError(msg) from exc
        finally:
            del data

    @final
    def incremental_deserialize(self) -> Generator[None, bytes, tuple[str, bytes]]:
        """
        Yields until `separator` is found and return the decoded string.

        See :meth:`.AbstractIncrementalPacketSerializer.incremental_deserialize` documentation for details.

        Raises:
            LimitOverrunError: Reached buffer size limit.
            IncrementalDeserializeError: :class:`UnicodeError` raised when decoding `data`.
        """
        reader = GeneratorStreamReader()
        data = yield from reader.read_until(self.__separator, limit=self.__limit, keep_end=self.__keep_end)
        remainder = reader.read_all()

        try:
            packet = str(data, self.__encoding, self.__unicode_errors)
        except UnicodeError as exc:
            msg = str(exc)
            if self.debug:
                raise IncrementalDeserializeError(msg, remainder, error_info={"data": data}) from exc
            raise IncrementalDeserializeError(msg, remainder) from exc
        finally:
            del data
        return packet, remainder

    @final
    def create_deserializer_buffer(self, sizehint: int) -> bytearray:
        """
        See :meth:`.BufferedIncrementalPacketSerializer.buffered_incremental_deserialize` documentation for details.
        """

        # Ignore sizehint, we have our own limit
        return bytearray(self.__limit)

    @final
    def buffered_incremental_deserialize(self, buffer: bytearray) -> Generator[int, int, tuple[str, memoryview]]:
        """
        Yields until `separator` is found and return the decoded string.

        See :meth:`.BufferedIncrementalPacketSerializer.buffered_incremental_deserialize` documentation for details.

        Raises:
            LimitOverrunError: Reached buffer size limit.
            IncrementalDeserializeError: :class:`UnicodeError` raised when decoding `data`.
        """
        with memoryview(buffer) as buffer_view:
            sepidx, offset, buflen = yield from _buffered_readuntil(buffer, self.__separator)
            del buffer

            remainder: memoryview = buffer_view[offset:buflen]
            with buffer_view[:offset] if self.__keep_end else buffer_view[:sepidx] as data:
                try:
                    packet = str(data, self.__encoding, self.__unicode_errors)
                except UnicodeError as exc:
                    msg = str(exc)
                    if self.debug:
                        raise IncrementalDeserializeError(msg, remainder, error_info={"data": bytes(data)}) from exc
                    raise IncrementalDeserializeError(msg, remainder) from exc
            return packet, remainder

    @property
    @final
    def separator(self) -> bytes:
        """
        Byte sequence that indicates the end of the token. Read-only attribute.
        """
        return self.__separator

    @property
    @final
    def debug(self) -> bool:
        """
        The debug mode flag. Read-only attribute.
        """
        return self.__debug

    @property
    @final
    def buffer_limit(self) -> int:
        """
        Maximum buffer size. Read-only attribute.
        """
        return self.__limit

    @property
    @final
    def keep_end(self) -> bool:
        """
        Specifies whether or not to preserve the separator during deserialization. Read-only attribute.
        """
        return self.__keep_end

    @property
    @final
    def encoding(self) -> str:
        """
        String encoding. Read-only attribute.
        """
        return self.__encoding

    @property
    @final
    def unicode_errors(self) -> str:
        """
        Controls how encoding errors are handled. Read-only attribute.
        """
        return self.__unicode_errors
