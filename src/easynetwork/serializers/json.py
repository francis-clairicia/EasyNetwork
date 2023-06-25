# -*- coding: utf-8 -*-
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

import string
from collections import Counter
from dataclasses import asdict as dataclass_asdict, dataclass
from typing import Any, Callable, Generator, TypeVar, final

from ..exceptions import DeserializeError, IncrementalDeserializeError
from ..tools._utils import iter_bytes
from .abc import AbstractIncrementalPacketSerializer

_ST_contra = TypeVar("_ST_contra", contravariant=True)
_DT_co = TypeVar("_DT_co", covariant=True)


_JSON_VALUE_BYTES: frozenset[int] = frozenset(bytes(string.digits + string.ascii_letters + string.punctuation, "ascii"))


@dataclass(kw_only=True)
class JSONEncoderConfig:
    skipkeys: bool = False
    check_circular: bool = True
    ensure_ascii: bool = True
    allow_nan: bool = True
    indent: int | None = None
    separators: tuple[str, str] | None = (",", ":")  # Compact JSON (w/o whitespaces)
    default: Callable[..., Any] | None = None


@dataclass(kw_only=True)
class JSONDecoderConfig:
    object_hook: Callable[..., Any] | None = None
    parse_int: Callable[[str], Any] | None = None
    parse_float: Callable[[str], Any] | None = None
    parse_constant: Callable[[str], Any] | None = None
    object_pairs_hook: Callable[[list[tuple[str, Any]]], Any] | None = None
    strict: bool = True


class _JSONParser:
    @staticmethod
    def _escaped(partial_document: bytes) -> bool:
        return ((len(partial_document) - len(partial_document.rstrip(b"\\"))) % 2) == 1

    @staticmethod
    def raw_parse() -> Generator[None, bytes, tuple[bytes, bytes]]:
        escaped = _JSONParser._escaped
        enclosure_counter: Counter[bytes] = Counter()
        partial_document: bytearray = bytearray()
        first_enclosure: bytes = b""
        while True:
            while not (chunk := (yield)):  # Skip empty bytes
                continue
            char: bytes
            for nb_chars, char in enumerate(iter_bytes(chunk), start=1):
                match char:
                    case b'"' if not escaped(partial_document):
                        enclosure_counter[b'"'] = 0 if enclosure_counter[b'"'] == 1 else 1
                    case _ if enclosure_counter[b'"'] > 0:
                        partial_document.extend(char)
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
                        return (yield from _JSONParser._raw_parse_plain_value(partial_document, chunk[nb_chars - 1 :]))
                assert len(enclosure_counter) > 0
                partial_document.extend(char)
                if not first_enclosure:
                    first_enclosure = next(iter(enclosure_counter))
                if enclosure_counter[first_enclosure] <= 0:  # 1st found is closed
                    return partial_document, chunk[nb_chars:]

    @staticmethod
    def _raw_parse_plain_value(buffer_array: bytearray, chunk: bytes) -> Generator[None, bytes, tuple[bytes, bytes]]:
        while True:
            non_printable_idx: int = next((idx for idx, byte in enumerate(chunk) if byte not in _JSON_VALUE_BYTES), -1)
            if non_printable_idx < 0:
                buffer_array.extend(chunk)
                while not (chunk := (yield)):
                    continue
                continue
            break
        buffer_array.extend(chunk[:non_printable_idx])
        return buffer_array, chunk[non_printable_idx:]


class JSONSerializer(AbstractIncrementalPacketSerializer[_ST_contra, _DT_co]):
    __slots__ = ("__encoder", "__decoder", "__decoder_error_cls", "__encoding", "__unicode_errors")

    def __init__(
        self,
        encoder_config: JSONEncoderConfig | None = None,
        decoder_config: JSONDecoderConfig | None = None,
        *,
        encoding: str = "utf-8",
        unicode_errors: str = "strict",
    ) -> None:
        from json import JSONDecodeError, JSONDecoder, JSONEncoder

        super().__init__()
        self.__encoder: JSONEncoder
        self.__decoder: JSONDecoder

        if encoder_config is None:
            encoder_config = JSONEncoderConfig()
        elif not isinstance(encoder_config, JSONEncoderConfig):
            raise TypeError(f"Invalid encoder config: expected {JSONEncoderConfig.__name__}, got {type(encoder_config).__name__}")

        if decoder_config is None:
            decoder_config = JSONDecoderConfig()
        elif not isinstance(decoder_config, JSONDecoderConfig):
            raise TypeError(f"Invalid decoder config: expected {JSONDecoderConfig.__name__}, got {type(decoder_config).__name__}")

        self.__encoder = JSONEncoder(**dataclass_asdict(encoder_config))
        self.__decoder = JSONDecoder(**dataclass_asdict(decoder_config))
        self.__decoder_error_cls = JSONDecodeError

        self.__encoding: str = encoding
        self.__unicode_errors: str = unicode_errors

    @final
    def serialize(self, packet: _ST_contra) -> bytes:
        return self.__encoder.encode(packet).encode(self.__encoding, self.__unicode_errors)

    @final
    def incremental_serialize(self, packet: _ST_contra) -> Generator[bytes, None, None]:
        encoding: str = self.__encoding
        str_errors: str = self.__unicode_errors
        for chunk in self.__encoder.iterencode(packet):
            yield chunk.encode(encoding, str_errors)
        yield b"\n"

    @final
    def deserialize(self, data: bytes) -> _DT_co:
        try:
            document: str = data.decode(self.__encoding, self.__unicode_errors)
        except UnicodeError as exc:
            raise DeserializeError(f"Unicode decode error: {exc}", error_info={"data": data}) from exc
        try:
            packet: _DT_co = self.__decoder.decode(document)
        except self.__decoder_error_cls as exc:
            raise DeserializeError(
                f"JSON decode error: {exc}",
                error_info={
                    "document": exc.doc,
                    "position": exc.pos,
                    "lineno": exc.lineno,
                    "colno": exc.colno,
                },
            ) from exc
        return packet

    @final
    def incremental_deserialize(self) -> Generator[None, bytes, tuple[_DT_co, bytes]]:
        complete_document, remaining_data = yield from _JSONParser.raw_parse()

        if not complete_document:
            complete_document = remaining_data
            remaining_data = b""

        packet: _DT_co
        try:
            document: str = complete_document.decode(self.__encoding, self.__unicode_errors)
        except UnicodeError as exc:
            raise IncrementalDeserializeError(
                f"Unicode decode error: {exc}",
                remaining_data=remaining_data,
                error_info={"data": complete_document},
            ) from exc
        try:
            packet, end = self.__decoder.raw_decode(document)
        except self.__decoder_error_cls as exc:
            raise IncrementalDeserializeError(
                f"JSON decode error: {exc}",
                remaining_data=remaining_data,
                error_info={
                    "document": exc.doc,
                    "position": exc.pos,
                    "lineno": exc.lineno,
                    "colno": exc.colno,
                },
            ) from exc
        try:
            remaining_data = document[end:].encode(self.__encoding, self.__unicode_errors) + remaining_data
        except UnicodeError:  # pragma: no cover  # Should not happen but it must not pass
            pass
        return packet, remaining_data.lstrip(b" \t\n\r")  # Optimization: Skip leading spaces
