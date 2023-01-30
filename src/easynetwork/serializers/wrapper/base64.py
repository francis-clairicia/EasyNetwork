# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""base64 encoding serializer module"""

from __future__ import annotations

__all__ = [
    "Base64EncodedSerializer",
]

import base64
import binascii
from hmac import compare_digest, digest as hmac_digest
from typing import TypeVar, final

from ..abc import AbstractPacketSerializer
from ..base_stream import AutoSeparatedPacketSerializer
from ..exceptions import DeserializeError

_ST_contra = TypeVar("_ST_contra", contravariant=True)
_DT_co = TypeVar("_DT_co", covariant=True)


class Base64EncodedSerializer(AutoSeparatedPacketSerializer[_ST_contra, _DT_co]):
    __slots__ = ("__serializer", "__signing_key")

    def __init__(
        self,
        serializer: AbstractPacketSerializer[_ST_contra, _DT_co],
        signing_key: str | bytes | None = None,
    ) -> None:
        super().__init__(separator=b"\r\n", keepends=False)
        assert isinstance(serializer, AbstractPacketSerializer)
        self.__serializer: AbstractPacketSerializer[_ST_contra, _DT_co] = serializer
        if signing_key is not None:
            try:
                signing_key = base64.urlsafe_b64decode(signing_key)
            except binascii.Error as exc:
                raise ValueError("signing key must be 32 url-safe base64-encoded bytes.") from exc
            if len(signing_key) != 32:
                raise ValueError("signing key must be 32 url-safe base64-encoded bytes.")
        self.__signing_key: bytes | None = signing_key

    @classmethod
    def generate_key(cls) -> bytes:
        from os import urandom

        return base64.urlsafe_b64encode(urandom(32))

    @final
    def serialize(self, packet: _ST_contra) -> bytes:
        data = self.__serializer.serialize(packet)
        if key := self.__signing_key:
            data += hmac_digest(key, data, "sha256")
        return base64.urlsafe_b64encode(data)

    @final
    def deserialize(self, data: bytes) -> _DT_co:
        try:
            data = base64.urlsafe_b64decode(data)
        except binascii.Error:
            raise DeserializeError("Invalid token") from None
        if key := self.__signing_key:
            data, signature = data[:-32], data[-32:]
            if not compare_digest(hmac_digest(key, data, "sha256"), signature):
                raise DeserializeError("Invalid token")
        return self.__serializer.deserialize(data)
