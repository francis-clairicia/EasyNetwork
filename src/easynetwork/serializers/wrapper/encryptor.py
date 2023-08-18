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
"""encrypted data serializer module"""

from __future__ import annotations

__all__ = [
    "EncryptorSerializer",
]

from typing import final

from ...exceptions import DeserializeError
from .._typevars import DeserializedPacketT_co, SerializedPacketT_contra
from ..abc import AbstractPacketSerializer
from ..base_stream import AutoSeparatedPacketSerializer


class EncryptorSerializer(AutoSeparatedPacketSerializer[SerializedPacketT_contra, DeserializedPacketT_co]):
    __slots__ = ("__serializer", "__fernet", "__token_ttl", "__invalid_token_cls")

    def __init__(
        self,
        serializer: AbstractPacketSerializer[SerializedPacketT_contra, DeserializedPacketT_co],
        key: str | bytes,
        *,
        token_ttl: int | None = None,
        separator: bytes = b"\r\n",
    ) -> None:
        try:
            import cryptography.fernet
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise ModuleNotFoundError("encryption dependencies are missing. Consider adding 'encryption' extra") from exc

        super().__init__(separator=separator, incremental_serialize_check_separator=not separator.isspace())
        if not isinstance(serializer, AbstractPacketSerializer):
            raise TypeError(f"Expected a serializer instance, got {serializer!r}")
        self.__serializer: AbstractPacketSerializer[SerializedPacketT_contra, DeserializedPacketT_co] = serializer
        self.__fernet = cryptography.fernet.Fernet(key)
        self.__token_ttl = token_ttl
        self.__invalid_token_cls = cryptography.fernet.InvalidToken

    @classmethod
    def generate_key(cls) -> bytes:
        try:
            import cryptography.fernet
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise ModuleNotFoundError("encryption dependencies are missing. Consider adding 'encryption' extra") from exc

        return cryptography.fernet.Fernet.generate_key()

    @final
    def serialize(self, packet: SerializedPacketT_contra) -> bytes:
        data = self.__serializer.serialize(packet)
        return self.__fernet.encrypt(data)

    @final
    def deserialize(self, data: bytes) -> DeserializedPacketT_co:
        try:
            data = self.__fernet.decrypt(data, ttl=self.__token_ttl)
        except self.__invalid_token_cls:
            raise DeserializeError("Invalid token", error_info=None) from None
        return self.__serializer.deserialize(data)
