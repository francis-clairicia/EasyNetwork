# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""json-based network packet serializer module"""

from __future__ import annotations

__all__ = [
    "JSONDecoderConfig",
    "JSONEncoderConfig",
    "JSONSerializer",
]

from collections import Counter
from dataclasses import asdict as dataclass_asdict, dataclass
from typing import Any, Callable, Generator, TypeVar, final

from .exceptions import DeserializeError
from .stream.abc import AbstractIncrementalPacketSerializer
from .stream.exceptions import IncrementalDeserializeError

_ST_contra = TypeVar("_ST_contra", contravariant=True, bound=list[Any] | dict[str, Any])
_DT_co = TypeVar("_DT_co", covariant=True, bound=list[Any] | dict[str, Any])


@dataclass(kw_only=True, frozen=True)
class JSONEncoderConfig:
    skipkeys: bool = False
    check_circular: bool = True
    ensure_ascii: bool = True
    allow_nan: bool = True
    indent: int | None = None
    separators: tuple[str, str] | None = (",", ":")  # Compact JSON (w/o whitespaces)
    default: Callable[..., Any] | None = None


@dataclass(kw_only=True, frozen=True)
class JSONDecoderConfig:
    object_hook: Callable[..., Any] | None = None
    parse_int: Callable[[str], Any] | None = None
    parse_float: Callable[[str], Any] | None = None
    parse_constant: Callable[[str], Any] | None = None
    object_pairs_hook: Callable[[list[tuple[str, Any]]], Any] | None = None
    strict: bool = True


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
                    case _ if len(enclosure_counter) == 0:  # No enclosure, only value
                        assert not partial_document
                        return (yield from _JSONParser._raw_parse_plain_value(char + chunk[nb_chars:]))
                partial_document += char
                if enclosure_counter[next(iter(enclosure_counter))] <= 0:  # 1st found is closed
                    complete_document = partial_document
                    partial_document = chunk[nb_chars:]
                    break
        return complete_document, partial_document

    @staticmethod
    def _raw_parse_plain_value(chunk: bytes) -> Generator[None, bytes, tuple[bytes, bytes]]:
        import struct

        result = bytearray(chunk)
        while not chunk or chunk.isalnum():
            chunk = yield
            result.extend(chunk)
        del chunk
        idx: int = next(idx for idx, char in enumerate(struct.unpack(f"{len(result)}c", result)) if not char.isalnum())
        return result[:idx], result[idx:]


class JSONSerializer(AbstractIncrementalPacketSerializer[_ST_contra, _DT_co]):
    __slots__ = ("__e", "__d")

    def __init__(self, *, encoder: JSONEncoderConfig | None = None, decoder: JSONDecoderConfig | None = None) -> None:
        from json import JSONDecoder, JSONEncoder

        super().__init__()
        self.__e: JSONEncoder
        self.__d: JSONDecoder

        if encoder is None:
            encoder = JSONEncoderConfig()
        elif not isinstance(encoder, JSONEncoderConfig):
            raise TypeError(f"Invalid encoder: expected {JSONEncoderConfig.__name__}, got {type(encoder).__name__}")
        self.__e = JSONEncoder(**dataclass_asdict(encoder))

        if decoder is None:
            decoder = JSONDecoderConfig()
        elif not isinstance(decoder, JSONDecoderConfig):
            raise TypeError(f"Invalid decoder: expected {JSONDecoderConfig.__name__}, got {type(decoder).__name__}")
        self.__d = JSONDecoder(**dataclass_asdict(decoder))

    @final
    def serialize(self, packet: _ST_contra) -> bytes:
        encoder = self.__e
        return encoder.encode(packet).encode("utf-8")

    @final
    def incremental_serialize(self, packet: _ST_contra) -> Generator[bytes, None, None]:
        encoder = self.__e
        for chunk in encoder.iterencode(packet):
            yield chunk.encode("utf-8")
        yield b"\n"

    @final
    def deserialize(self, data: bytes) -> _DT_co:
        from json import JSONDecodeError

        try:
            document: str = data.decode("utf-8")
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
        from json import JSONDecodeError

        complete_document, remaining_data = yield from _JSONParser.raw_parse()

        if not complete_document:
            complete_document = remaining_data
            remaining_data = b""

        decoder = self.__d
        packet: _DT_co
        try:
            document: str = complete_document.decode("utf-8")
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
        return packet, (document[end:].encode("utf-8") + remaining_data).lstrip(b" \t\n\r")
