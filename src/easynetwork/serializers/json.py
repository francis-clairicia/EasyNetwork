# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""json-based network packet serializer module"""

from __future__ import annotations

__all__ = ["JSONSerializer"]

from collections import Counter
from json import JSONDecodeError, JSONDecoder, JSONEncoder
from typing import Generator, TypeVar, final

from .exceptions import DeserializeError
from .stream.abc import IncrementalPacketSerializer
from .stream.exceptions import IncrementalDeserializeError

_ST_contra = TypeVar("_ST_contra", contravariant=True)
_DT_co = TypeVar("_DT_co", covariant=True)


class _JSONParser:
    @staticmethod
    def raw_parse() -> Generator[None, bytes, tuple[bytes, bytes]]:
        import struct

        def escaped(partial_document: bytes) -> bool:
            return ((len(partial_document) - len(partial_document.rstrip(b"\\"))) % 2) == 1

        enclosure_counter: Counter[bytes] = Counter()
        partial_document: bytes = b""
        complete_document: bytes = b""
        while not complete_document:
            if not partial_document:
                enclosure_counter.clear()
            while not (chunk := (yield)):  # Skip empty bytes
                continue
            char: bytes
            for nb_chars, char in enumerate(struct.unpack(f"{len(chunk)}c", chunk), start=1):
                match char:
                    case b'"' if not escaped(partial_document):
                        enclosure_counter[b'"'] = 0 if enclosure_counter[b'"'] == 1 else 1
                    case _ if enclosure_counter[b'"'] > 0:
                        partial_document += char
                        continue
                    case b"{" | b"[":
                        enclosure_counter[char] += 1
                    case b"}":
                        enclosure_counter[b"{"] -= 1
                    case b"]":
                        enclosure_counter[b"["] -= 1
                    case b" " | b"\t" | b"\n" | b"\r":  # Optimization: Skip spaces
                        continue
                    case _ if not enclosure_counter:  # No enclosure, only value
                        # Directly refused because we cannot know when data is valid
                        raise IncrementalDeserializeError(
                            "Do not received beginning of a string/array/object",
                            remaining_data=chunk[nb_chars:],
                        )
                partial_document += char
                if enclosure_counter[next(iter(enclosure_counter))] <= 0:  # 1st found is closed
                    complete_document = partial_document
                    partial_document = chunk[nb_chars:]
                    break
        return complete_document, partial_document


class JSONSerializer(IncrementalPacketSerializer[_ST_contra, _DT_co]):
    __slots__ = ("__e", "__d")

    def __init__(self, *, encoder: JSONEncoder | None = None, decoder: JSONDecoder | None = None) -> None:
        super().__init__()
        self.__e: JSONEncoder
        self.__d: JSONDecoder
        match encoder:
            case None:
                self.__e = JSONEncoder(
                    skipkeys=False,
                    ensure_ascii=False,  # Unicode are accepted
                    check_circular=True,
                    allow_nan=True,
                    indent=None,
                    separators=(",", ":"),  # Compact JSON (w/o whitespaces)
                    default=None,
                )
            case JSONEncoder():
                self.__e = encoder
            case _:
                raise TypeError(f"Invalid encoder: expected json.JSONEncoder, got {type(encoder).__name__}")

        match decoder:
            case None:
                self.__d = JSONDecoder(object_hook=None, object_pairs_hook=None, strict=True)
            case JSONDecoder():
                self.__d = decoder
            case _:
                raise TypeError(f"Invalid decoder: expected json.JSONDecoder, got {type(decoder).__name__}")

    @final
    def serialize(self, packet: _ST_contra) -> bytes:
        encoder = self.__e
        encoding: str = "ascii" if encoder.ensure_ascii else "utf-8"
        return encoder.encode(packet).encode(encoding)

    @final
    def incremental_serialize(self, packet: _ST_contra) -> Generator[bytes, None, None]:
        encoder = self.__e
        encoding: str = "ascii" if encoder.ensure_ascii else "utf-8"
        encode_iterator = encoder.iterencode(packet)
        try:
            chunk = next(encode_iterator)
        except StopIteration:
            return
        if chunk[0] not in ("{", "[", '"'):
            raise ValueError("Plain values (except strings) forbidden in incremental context")
        yield chunk.encode(encoding)
        for chunk in encode_iterator:
            yield chunk.encode(encoding)

    def get_encoder(self) -> JSONEncoder:
        return self.__e

    @final
    def deserialize(self, data: bytes) -> _DT_co:
        data = data.strip(b" \t\n\r")
        if not data:
            raise DeserializeError("Empty bytes after stripping whitespaces")
        try:
            document: str = data.decode(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise DeserializeError(f"Unicode decode error: {exc}") from exc
        decoder = self.__d
        try:
            packet: _DT_co = decoder.decode(document)
        except JSONDecodeError as exc:
            raise DeserializeError(f"JSON decode error: {exc}") from exc
        return packet

    @final
    def incremental_deserialize(self) -> Generator[None, bytes, tuple[_DT_co, bytes]]:
        encoding: str = "utf-8"
        complete_document, remaining_data = yield from _JSONParser.raw_parse()

        decoder = self.__d
        packet: _DT_co
        try:
            document: str = complete_document.decode(encoding)
        except UnicodeDecodeError as exc:
            raise IncrementalDeserializeError(
                f"Unicode decode error: {exc}",
                remaining_data=remaining_data,
            ) from exc
        try:
            packet, end = decoder.raw_decode(document)
        except JSONDecodeError as exc:
            raise IncrementalDeserializeError(
                f"JSON decode error: {exc}",
                remaining_data=remaining_data,
            ) from exc
        return packet, (document[end:].encode(encoding) + remaining_data).lstrip(b" \t\n\r")

    def get_decoder(self) -> JSONDecoder:
        return self.__d
