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

import re
import string
from collections import Counter
from collections.abc import Callable, Generator
from dataclasses import asdict as dataclass_asdict, dataclass
from typing import Any, TypeVar, final

from ..exceptions import DeserializeError, IncrementalDeserializeError
from ..tools._utils import iter_bytes
from .abc import AbstractIncrementalPacketSerializer

_ST_contra = TypeVar("_ST_contra", contravariant=True)
_DT_co = TypeVar("_DT_co", covariant=True)


_JSON_VALUE_BYTES: frozenset[int] = frozenset(bytes(string.digits + string.ascii_letters + string.punctuation, "ascii"))
_ESCAPE_BYTE: int = b"\\"[0]

_whitespaces_match: Callable[[bytes, int], re.Match[bytes]] = re.compile(rb"[ \t\n\r]*", re.MULTILINE | re.DOTALL).match  # type: ignore[assignment]


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
    class _PlainValueError(Exception):
        pass

    @staticmethod
    def _escaped(partial_document_view: memoryview) -> bool:
        escaped = False
        for byte in reversed(partial_document_view):
            if byte == _ESCAPE_BYTE:
                escaped = not escaped
            else:
                break
        return escaped

    @staticmethod
    def raw_parse() -> Generator[None, bytes, tuple[bytes, bytes]]:
        escaped = _JSONParser._escaped
        split_partial_document = _JSONParser._split_partial_document
        enclosure_counter: Counter[bytes] = Counter()
        partial_document: bytes = yield
        first_enclosure: bytes = b""
        start: int = 0
        try:
            while True:
                with memoryview(partial_document) as partial_document_view:
                    for nb_chars, char in enumerate(iter_bytes(partial_document_view[start:]), start=start + 1):
                        match char:
                            case b'"' if not escaped(partial_document_view[: nb_chars - 1]):
                                enclosure_counter[b'"'] = 0 if enclosure_counter[b'"'] == 1 else 1
                            case _ if enclosure_counter[b'"'] > 0:  # We are within a JSON string, move on.
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
                                partial_document = partial_document[nb_chars - 1 :] if nb_chars > 1 else partial_document
                                del char, nb_chars
                                raise _JSONParser._PlainValueError
                            case _:  # JSON character, quickly go to next character
                                continue
                        assert len(enclosure_counter) > 0  # nosec assert_used
                        if not first_enclosure:
                            first_enclosure = next(iter(enclosure_counter))
                        if enclosure_counter[first_enclosure] <= 0:  # 1st found is closed
                            return split_partial_document(partial_document, nb_chars)

                    # partial_document not complete
                    start = partial_document_view.nbytes

                # yield out of view scope
                partial_document += yield

        except _JSONParser._PlainValueError:
            pass

        # The document is a plain value (null, true, false, or a number)

        del enclosure_counter, first_enclosure

        while (nprint_idx := next((idx for idx, byte in enumerate(partial_document) if byte not in _JSON_VALUE_BYTES), -1)) < 0:
            partial_document += yield

        return split_partial_document(partial_document, nprint_idx)

    @staticmethod
    def _split_partial_document(partial_document: bytes, index: int) -> tuple[bytes, bytes]:
        index = _whitespaces_match(partial_document, index).end()
        if index == len(partial_document):
            # The following bytes are only spaces
            # Do not slice the document, the trailing spaces will be ignored by JSONDecoder
            return partial_document, b""
        return partial_document[:index], partial_document[index:]


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
        yield self.__encoder.encode(packet).encode(self.__encoding, self.__unicode_errors)
        yield b"\n"

    @final
    def deserialize(self, data: bytes) -> _DT_co:
        try:
            document: str = data.decode(self.__encoding, self.__unicode_errors)
        except UnicodeError as exc:
            raise DeserializeError(f"Unicode decode error: {exc}", error_info={"data": data}) from exc
        finally:
            del data
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
            # If this condition is verified, decoder.decode() will most likely raise JSONDecodeError
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
        finally:
            del complete_document
        try:
            packet = self.__decoder.decode(document)
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
        return packet, remaining_data
