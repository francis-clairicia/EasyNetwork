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
"""string line packet serializer module"""

from __future__ import annotations

__all__ = ["StringLineSerializer"]

from typing import Literal, assert_never, final

from ..exceptions import DeserializeError
from .base_stream import AutoSeparatedPacketSerializer


class StringLineSerializer(AutoSeparatedPacketSerializer[str, str]):
    """
    A :term:`serializer` to handle ASCII-based protocols.
    """

    __slots__ = ("__encoding", "__unicode_errors")

    def __init__(
        self,
        newline: Literal["LF", "CR", "CRLF"] = "LF",
        *,
        encoding: str = "ascii",
        unicode_errors: str = "strict",
    ) -> None:
        r"""
        Arguments:
            newline: Magic string indicating the newline character sequence.
                     Possible values are:

                     - ``"LF"`` (the default): Line feed character (``"\n"``).

                     - ``"CR"``: Carriage return character (``"\r"``).

                     - ``"CRLF"``: Carriage return + line feed character sequence (``"\r\n"``).
            encoding: String encoding. Defaults to ``"ascii"``.
            unicode_errors: Controls how encoding errors are handled.

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
        super().__init__(separator=separator, incremental_serialize_check_separator=False)
        self.__encoding: str = encoding
        self.__unicode_errors: str = unicode_errors

    @final
    def serialize(self, packet: str) -> bytes:
        """
        Encodes the given string to bytes.

        Roughly equivalent to::

            def serialize(self, packet):
                return packet.encode()

        Example:
            >>> from easynetwork.serializers import StringLineSerializer
            >>> s = StringLineSerializer()
            >>> s.serialize("character string")
            b'character string'

        Arguments:
            packet: The string to encode.

        Raises:
            TypeError: `packet` is not a :class:`str`.
            UnicodeError: Invalid string.
            ValueError: `newline` found in `packet`.

        Returns:
            the byte sequence.

        Important:
            The output **does not** contain `newline`.
        """
        if not isinstance(packet, str):
            raise TypeError(f"Expected a string, got {packet!r}")
        data = packet.encode(self.__encoding, self.__unicode_errors)
        if self.separator in data:
            raise ValueError("Newline found in string")
        return data

    @final
    def deserialize(self, data: bytes) -> str:
        r"""
        Decodes `data` and returns the string.

        Roughly equivalent to::

            def deserialize(self, data):
                return data.decode()

        Example:
            >>> from easynetwork.serializers import StringLineSerializer
            >>> s = StringLineSerializer()
            >>> s.deserialize(b"character string")
            'character string'

        Arguments:
            packet: The data to decode.

        Raises:
            DeserializeError: :class:`UnicodeError` raised when decoding `data`.

        Returns:
            the string.

        Important:
            Trailing `newline` sequences are **removed**.
        """
        separator: bytes = self.separator
        while data.endswith(separator):
            data = data.removesuffix(separator)
        try:
            return data.decode(self.__encoding, self.__unicode_errors)
        except UnicodeError as exc:
            raise DeserializeError(str(exc), error_info={"data": data}) from exc

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
