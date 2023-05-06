# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""encrypted data serializer module"""

from __future__ import annotations

__all__ = [
    "EncryptorSerializer",
]

from typing import TypeVar, final

from ...exceptions import DeserializeError
from ..abc import AbstractPacketSerializer
from ..base_stream import AutoSeparatedPacketSerializer

_ST_contra = TypeVar("_ST_contra", contravariant=True)
_DT_co = TypeVar("_DT_co", covariant=True)


class EncryptorSerializer(AutoSeparatedPacketSerializer[_ST_contra, _DT_co]):
    __slots__ = ("__serializer", "__fernet", "__token_ttl")

    def __init__(
        self,
        serializer: AbstractPacketSerializer[_ST_contra, _DT_co],
        key: str | bytes,
        *,
        token_ttl: int | None = None,
        separator: bytes = b"\r\n",
    ) -> None:
        try:
            import cryptography.fernet
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise ModuleNotFoundError("encryption dependencies are missing. Consider adding 'encryption' extra") from exc

        super().__init__(separator=separator, keepends=False)
        assert isinstance(serializer, AbstractPacketSerializer)
        self.__serializer: AbstractPacketSerializer[_ST_contra, _DT_co] = serializer
        self.__fernet = cryptography.fernet.Fernet(key)
        self.__token_ttl = token_ttl

    @classmethod
    def generate_key(cls) -> bytes:
        try:
            import cryptography.fernet
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise ModuleNotFoundError("encryption dependencies are missing. Consider adding 'encryption' extra") from exc

        return cryptography.fernet.Fernet.generate_key()

    @final
    def serialize(self, packet: _ST_contra) -> bytes:
        data = self.__serializer.serialize(packet)
        return self.__fernet.encrypt(data)

    @final
    def deserialize(self, data: bytes) -> _DT_co:
        from cryptography.fernet import InvalidToken

        try:
            data = self.__fernet.decrypt(data, ttl=self.__token_ttl)
        except InvalidToken:
            raise DeserializeError("Invalid token") from None
        return self.__serializer.deserialize(data)
