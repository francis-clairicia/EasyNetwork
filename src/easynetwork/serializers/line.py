# -*- coding: Utf-8 -*-
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
    __slots__ = ("__encoding", "__on_str_error")

    def __init__(
        self,
        newline: Literal["LF", "CR", "CRLF"] = "LF",
        *,
        keepends: bool = False,
        encoding: str = "ascii",
        on_str_error: str = "strict",
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
        super().__init__(separator=separator, keepends=keepends)
        self.__encoding: str = encoding
        self.__on_str_error: str = on_str_error

    @final
    def serialize(self, packet: str) -> bytes:
        if not isinstance(packet, str):
            raise TypeError(f"Expected a string, got {packet!r}")
        return packet.encode(self.__encoding, self.__on_str_error)

    @final
    def deserialize(self, data: bytes) -> str:
        try:
            return data.decode(self.__encoding, self.__on_str_error)
        except UnicodeError as exc:
            raise DeserializeError(str(exc)) from exc

    @property
    def encoding(self) -> str:
        return self.__encoding

    @property
    def on_string_error(self) -> str:
        return self.__on_str_error
