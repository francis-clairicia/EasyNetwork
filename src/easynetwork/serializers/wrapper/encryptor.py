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

from ..._typevars import _DTOPacketT
from ...exceptions import DeserializeError
from ...tools.constants import _DEFAULT_LIMIT
from ..abc import AbstractPacketSerializer
from ..base_stream import AutoSeparatedPacketSerializer


class EncryptorSerializer(AutoSeparatedPacketSerializer[_DTOPacketT]):
    """
    A :term:`serializer wrapper` to handle encrypted data, built on top of :mod:`cryptography.fernet` module.

    Needs ``encryption`` extra dependencies.
    """

    __slots__ = ("__serializer", "__fernet", "__token_ttl", "__invalid_token_cls")

    def __init__(
        self,
        serializer: AbstractPacketSerializer[_DTOPacketT],
        key: str | bytes,
        *,
        token_ttl: int | None = None,
        separator: bytes = b"\r\n",
        limit: int = _DEFAULT_LIMIT,
    ) -> None:
        """
        Parameters:
            serializer: The serializer to wrap.
            key: A URL-safe base64-encoded 32-byte key.
            token_ttl: Token time-to-live. See :meth:`cryptography.fernet.Fernet.decrypt` for details.
            separator: Token for :class:`AutoSeparatedPacketSerializer`. Used in incremental serialization context.
            limit: Maximum buffer size. Used in incremental serialization context.
        """
        try:
            import cryptography.fernet
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise ModuleNotFoundError("encryption dependencies are missing. Consider adding 'encryption' extra") from exc

        super().__init__(separator=separator, incremental_serialize_check_separator=not separator.isspace(), limit=limit)
        if not isinstance(serializer, AbstractPacketSerializer):
            raise TypeError(f"Expected a serializer instance, got {serializer!r}")
        self.__serializer: AbstractPacketSerializer[_DTOPacketT] = serializer
        self.__fernet = cryptography.fernet.Fernet(key)
        self.__token_ttl = token_ttl
        self.__invalid_token_cls = cryptography.fernet.InvalidToken

    @classmethod
    def generate_key(cls) -> bytes:
        """
        Generates a fresh key suitable for encryption.

        Keep this some place safe!

        Implementation details:
            Delegates to :meth:`cryptography.fernet.Fernet.generate_key`.
        """
        try:
            import cryptography.fernet
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise ModuleNotFoundError("encryption dependencies are missing. Consider adding 'encryption' extra") from exc

        return cryptography.fernet.Fernet.generate_key()

    @final
    def serialize(self, packet: _DTOPacketT) -> bytes:
        """
        Serializes `packet` and encrypt the result.

        Parameters:
            packet: The Python object to serialize.

        Returns:
            a byte sequence.
        """
        data = self.__serializer.serialize(packet)
        return self.__fernet.encrypt(data)

    @final
    def deserialize(self, data: bytes) -> _DTOPacketT:
        """
        Decrypts token `data` and deserializes the result.

        Parameters:
            data: The byte sequence to deserialize.

        Raises:
            DeserializeError: Invalid base64 token.
            Exception: The underlying serializer raised an exception.

        Returns:
            the deserialized Python object.
        """
        try:
            data = self.__fernet.decrypt(data, ttl=self.__token_ttl)
        except self.__invalid_token_cls:
            raise DeserializeError("Invalid token", error_info=None) from None
        return self.__serializer.deserialize(data)
