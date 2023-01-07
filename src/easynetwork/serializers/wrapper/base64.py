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
from typing import TypeVar, final

from ..abc import AbstractPacketSerializer
from ..exceptions import DeserializeError
from ..stream.abc import AutoSeparatedPacketSerializer

_ST_contra = TypeVar("_ST_contra", contravariant=True)
_DT_co = TypeVar("_DT_co", covariant=True)


class Base64EncodedSerializer(AutoSeparatedPacketSerializer[_ST_contra, _DT_co]):
    __slots__ = ("__serializer",)

    def __init__(self, serializer: AbstractPacketSerializer[_ST_contra, _DT_co]) -> None:
        assert isinstance(serializer, AbstractPacketSerializer)
        super().__init__(separator=b"\r\n", keepends=False)
        self.__serializer: AbstractPacketSerializer[_ST_contra, _DT_co] = serializer

    @final
    def serialize(self, packet: _ST_contra) -> bytes:
        return base64.standard_b64encode(self.__serializer.serialize(packet))

    @final
    def deserialize(self, data: bytes) -> _DT_co:
        try:
            data = base64.standard_b64decode(data)
        except binascii.Error as exc:
            raise DeserializeError("base64 decoding error") from exc
        return self.__serializer.deserialize(data)
