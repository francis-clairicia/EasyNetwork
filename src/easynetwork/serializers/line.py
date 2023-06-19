# -*- coding: utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""string line network packet serializer module"""

from __future__ import annotations

__all__ = ["StringLineSerializer"]

from typing import Literal, assert_never, final

from ..exceptions import DeserializeError
from .base_stream import AutoSeparatedPacketSerializer


class StringLineSerializer(AutoSeparatedPacketSerializer[str, str]):
    __slots__ = ("__encoding", "__unicode_errors")

    def __init__(
        self,
        newline: Literal["LF", "CR", "CRLF"] = "LF",
        *,
        encoding: str = "ascii",
        unicode_errors: str = "strict",
    ) -> None:
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
        super().__init__(separator=separator)
        self.__encoding: str = encoding
        self.__unicode_errors: str = unicode_errors

    @final
    def serialize(self, packet: str) -> bytes:
        if not isinstance(packet, str):
            raise TypeError(f"Expected a string, got {packet!r}")
        if len(packet) == 0:
            raise ValueError("Empty packet")
        data = packet.encode(self.__encoding, self.__unicode_errors)
        if self.separator in data:
            raise ValueError("Newline found in string")
        return data

    @final
    def deserialize(self, data: bytes) -> str:
        separator: bytes = self.separator
        while data.endswith(separator):
            data = data.removesuffix(separator)
        if len(data) == 0:
            raise DeserializeError("Empty packet", error_info={"data": data})
        if separator in data:
            raise DeserializeError("Newline found in data which was not at the end", error_info={"data": data})
        try:
            return data.decode(self.__encoding, self.__unicode_errors)
        except UnicodeError as exc:
            raise DeserializeError(str(exc), error_info={"data": data}) from exc

    @property
    def encoding(self) -> str:
        return self.__encoding

    @property
    def unicode_errors(self) -> str:
        return self.__unicode_errors
