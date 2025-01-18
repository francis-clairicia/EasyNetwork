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
"""base64 encoder serializer module."""

from __future__ import annotations

__all__ = [
    "Base64EncoderSerializer",
]

import os
from collections.abc import Callable
from typing import Literal, final

from ..._typevars import _T_ReceivedDTOPacket, _T_SentDTOPacket
from ...exceptions import DeserializeError
from ...lowlevel.constants import DEFAULT_SERIALIZER_LIMIT
from ..abc import AbstractPacketSerializer
from ..base_stream import AutoSeparatedPacketSerializer


class Base64EncoderSerializer(AutoSeparatedPacketSerializer[_T_SentDTOPacket, _T_ReceivedDTOPacket]):
    """
    A :term:`serializer wrapper` to handle base64 encoded data, built on top of :mod:`base64` module.
    """

    __slots__ = ("__serializer", "__encode", "__decode", "__compare_digest", "__decode_error_cls", "__checksum")

    def __init__(
        self,
        serializer: AbstractPacketSerializer[_T_SentDTOPacket, _T_ReceivedDTOPacket],
        *,
        alphabet: Literal["standard", "urlsafe"] = "urlsafe",
        checksum: bool | str | bytes = False,
        separator: bytes = b"\r\n",
        limit: int = DEFAULT_SERIALIZER_LIMIT,
        debug: bool = False,
    ) -> None:
        """
        Parameters:
            serializer: The serializer to wrap.
            alphabet: The base64 alphabet to use. Possible values are:

                      - ``"standard"``: Use standard alphabet.

                      - ``"urlsafe"``: Use URL- and filesystem-safe alphabet.

                      Defaults to ``"urlsafe"``.
            checksum: If `True`, appends a sha256 checksum to the serialized data.
                      `checksum` can also be a URL-safe base64-encoded 32-byte key for a signed checksum.
            separator: Token for :class:`AutoSeparatedPacketSerializer`. Used in incremental serialization context.
            limit: Maximum buffer size. Used in incremental serialization context.
            debug: If :data:`True`, add information to :exc:`.DeserializeError` via the ``error_info`` attribute.
        """
        import base64
        import binascii
        from hmac import compare_digest

        super().__init__(
            separator=separator,
            incremental_serialize_check_separator=not separator.isspace(),
            limit=limit,
            debug=debug,
        )
        if not isinstance(serializer, AbstractPacketSerializer):
            raise TypeError(f"Expected a serializer instance, got {serializer!r}")
        self.__serializer: AbstractPacketSerializer[_T_SentDTOPacket, _T_ReceivedDTOPacket] = serializer
        self.__checksum: Callable[[bytes], bytes] | None
        match checksum:
            case False:
                self.__checksum = None
            case True:
                from hashlib import sha256 as hashlib_sha256

                self.__checksum = lambda data: hashlib_sha256(data).digest()
            case str() | bytes():
                from hmac import digest as hmac_digest

                try:
                    key: bytes = base64.urlsafe_b64decode(checksum)
                except binascii.Error as exc:
                    raise ValueError("signing key must be 32 url-safe base64-encoded bytes.") from exc
                if len(key) != 32:
                    raise ValueError("signing key must be 32 url-safe base64-encoded bytes.")
                self.__checksum = lambda data: hmac_digest(key, data, "sha256")
            case _:
                raise TypeError("Invalid checksum argument")

        match alphabet:
            case "standard":
                self.__encode = base64.standard_b64encode
                self.__decode = base64.standard_b64decode
            case "urlsafe":
                self.__encode = base64.urlsafe_b64encode
                self.__decode = base64.urlsafe_b64decode
            case _:
                raise TypeError("Invalid alphabet argument")

        self.__decode_error_cls = binascii.Error
        self.__compare_digest = compare_digest

    @classmethod
    def generate_key(cls) -> bytes:
        """
        Generates a fresh key suitable for signed checksums.

        Keep this some place safe!
        """
        import base64

        return base64.urlsafe_b64encode(os.urandom(32))

    @final
    def serialize(self, packet: _T_SentDTOPacket) -> bytes:
        """
        Serializes `packet` and encodes the result in base64.

        Parameters:
            packet: The Python object to serialize.

        Returns:
            a byte sequence.
        """
        data = self.__serializer.serialize(packet)
        if (checksum := self.__checksum) is not None:
            data += checksum(data)
        return self.__encode(data)

    @final
    def deserialize(self, data: bytes) -> _T_ReceivedDTOPacket:
        """
        Decodes base64 token `data` and deserializes the result.

        Parameters:
            data: The byte sequence to deserialize.

        Raises:
            DeserializeError: Invalid base64 token.
            Exception: The underlying serializer raised an exception.

        Returns:
            the deserialized Python object.
        """
        try:
            data = self.__decode(data)
        except self.__decode_error_cls:
            raise DeserializeError("Invalid token") from None
        if (checksum := self.__checksum) is not None:
            data, digest = data[:-32], data[-32:]
            if not self.__compare_digest(checksum(data), digest):
                raise DeserializeError("Invalid token")
        return self.__serializer.deserialize(data)
