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
"""base64 encoding serializer module"""

from __future__ import annotations

__all__ = [
    "Base64EncoderSerializer",
]

import os
from collections.abc import Callable
from typing import Literal, assert_never, final

from ...exceptions import DeserializeError
from .._typevars import DeserializedPacketT_co, SerializedPacketT_contra
from ..abc import AbstractPacketSerializer
from ..base_stream import AutoSeparatedPacketSerializer


class Base64EncoderSerializer(AutoSeparatedPacketSerializer[SerializedPacketT_contra, DeserializedPacketT_co]):
    __slots__ = ("__serializer", "__encode", "__decode", "__compare_digest", "__decode_error_cls", "__checksum")

    def __init__(
        self,
        serializer: AbstractPacketSerializer[SerializedPacketT_contra, DeserializedPacketT_co],
        *,
        alphabet: Literal["standard", "urlsafe"] = "urlsafe",
        checksum: bool | str | bytes = False,
        separator: bytes = b"\r\n",
    ) -> None:
        import base64
        import binascii
        from hashlib import sha256 as hashlib_sha256
        from hmac import compare_digest, digest as hmac_digest

        super().__init__(separator=separator, incremental_serialize_check_separator=not separator.isspace())
        if not isinstance(serializer, AbstractPacketSerializer):
            raise TypeError(f"Expected a serializer instance, got {serializer!r}")
        self.__serializer: AbstractPacketSerializer[SerializedPacketT_contra, DeserializedPacketT_co] = serializer
        self.__checksum: Callable[[bytes], bytes] | None
        match checksum:
            case False:
                self.__checksum = None
            case True:
                self.__checksum = lambda data: hashlib_sha256(data).digest()
            case str() | bytes():
                try:
                    key: bytes = base64.urlsafe_b64decode(checksum)
                except binascii.Error as exc:
                    raise ValueError("signing key must be 32 url-safe base64-encoded bytes.") from exc
                if len(key) != 32:
                    raise ValueError("signing key must be 32 url-safe base64-encoded bytes.")
                self.__checksum = lambda data: hmac_digest(key, data, "sha256")
            case _:  # pragma: no cover
                assert_never(checksum)

        match alphabet:
            case "standard":
                self.__encode = base64.standard_b64encode
                self.__decode = base64.standard_b64decode
            case "urlsafe":
                self.__encode = base64.urlsafe_b64encode
                self.__decode = base64.urlsafe_b64decode
            case _:  # pragma: no cover
                assert_never(alphabet)

        self.__decode_error_cls = binascii.Error
        self.__compare_digest = compare_digest

    @classmethod
    def generate_key(cls) -> bytes:
        import base64

        return base64.urlsafe_b64encode(os.urandom(32))

    @final
    def serialize(self, packet: SerializedPacketT_contra) -> bytes:
        data = self.__serializer.serialize(packet)
        if (checksum := self.__checksum) is not None:
            data += checksum(data)
        return self.__encode(data)

    @final
    def deserialize(self, data: bytes) -> DeserializedPacketT_co:
        try:
            data = self.__decode(data)
        except self.__decode_error_cls:
            raise DeserializeError("Invalid token") from None
        if (checksum := self.__checksum) is not None:
            data, digest = data[:-32], data[-32:]
            if not self.__compare_digest(checksum(data), digest):
                raise DeserializeError("Invalid token", error_info=None)
        return self.__serializer.deserialize(data)
