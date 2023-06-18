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
from hashlib import sha256 as hashlib_sha256
from hmac import compare_digest, digest as hmac_digest
from typing import Callable, TypeVar, assert_never, final

from ...exceptions import DeserializeError
from ..abc import AbstractPacketSerializer
from ..base_stream import AutoSeparatedPacketSerializer

_ST_contra = TypeVar("_ST_contra", contravariant=True)
_DT_co = TypeVar("_DT_co", covariant=True)


class Base64EncodedSerializer(AutoSeparatedPacketSerializer[_ST_contra, _DT_co]):
    __slots__ = ("__serializer", "__checksum")

    def __init__(
        self,
        serializer: AbstractPacketSerializer[_ST_contra, _DT_co],
        *,
        checksum: bool | str | bytes = False,
        separator: bytes = b"\r\n",
    ) -> None:
        super().__init__(separator=separator)
        assert isinstance(serializer, AbstractPacketSerializer)
        self.__serializer: AbstractPacketSerializer[_ST_contra, _DT_co] = serializer
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

    @classmethod
    def generate_key(cls) -> bytes:
        from os import urandom

        return base64.urlsafe_b64encode(urandom(32))

    @final
    def serialize(self, packet: _ST_contra) -> bytes:
        data = self.__serializer.serialize(packet)
        if (checksum := self.__checksum) is not None:
            data += checksum(data)
        return base64.urlsafe_b64encode(data)

    @final
    def deserialize(self, data: bytes) -> _DT_co:
        try:
            data = base64.urlsafe_b64decode(data)
        except binascii.Error:
            raise DeserializeError("Invalid token") from None
        if (checksum := self.__checksum) is not None:
            data, digest = data[:-32], data[-32:]
            if not compare_digest(checksum(data), digest):
                raise DeserializeError("Invalid token", error_info=None)
        return self.__serializer.deserialize(data)
