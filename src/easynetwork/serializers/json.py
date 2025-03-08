# Copyright 2021-2025, Francis Clairicia-Rose-Claire-Josephine
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
#
"""``json``-based packet serializer module."""

from __future__ import annotations

__all__ = [
    "JSONDecoderConfig",
    "JSONEncoderConfig",
    "JSONSerializer",
]


import re
from collections.abc import Callable, Generator
from dataclasses import asdict as dataclass_asdict, dataclass
from typing import TYPE_CHECKING, Any, final

from ..exceptions import DeserializeError, IncrementalDeserializeError, LimitOverrunError
from ..lowlevel.constants import DEFAULT_SERIALIZER_LIMIT
from .abc import AbstractIncrementalPacketSerializer
from .tools import GeneratorStreamReader

if TYPE_CHECKING:
    from _typeshed import ReadableBuffer

_OBJECT_START = (b"{", b"[", b'"')


@dataclass(kw_only=True)
class JSONEncoderConfig:
    """
    A dataclass with the JSON encoder options.

    See :class:`json.JSONEncoder` for details.
    """

    skipkeys: bool = False
    check_circular: bool = True
    ensure_ascii: bool = True
    allow_nan: bool = True
    default: Callable[..., Any] | None = None


@dataclass(kw_only=True)
class JSONDecoderConfig:
    """
    A dataclass with the JSON decoder options.

    See :class:`json.JSONDecoder` for details.
    """

    object_hook: Callable[..., Any] | None = None
    parse_int: Callable[[str], Any] | None = None
    parse_float: Callable[[str], Any] | None = None
    parse_constant: Callable[[str], Any] | None = None
    object_pairs_hook: Callable[[list[tuple[str, Any]]], Any] | None = None
    strict: bool = True


class JSONSerializer(AbstractIncrementalPacketSerializer[Any, Any]):
    """
    A :term:`serializer` built on top of the :mod:`json` module.
    """

    __slots__ = (
        "__encoder",
        "__decoder",
        "__decoder_error_cls",
        "__encoding",
        "__unicode_errors",
        "__limit",
        "__use_lines",
        "__debug",
    )

    def __init__(
        self,
        encoder_config: JSONEncoderConfig | None = None,
        decoder_config: JSONDecoderConfig | None = None,
        *,
        encoding: str = "utf-8",
        unicode_errors: str = "strict",
        limit: int = DEFAULT_SERIALIZER_LIMIT,
        use_lines: bool = True,
        debug: bool = False,
    ) -> None:
        """
        Parameters:
            encoder_config: Parameter object to configure the :class:`~json.JSONEncoder`.
            decoder_config: Parameter object to configure the :class:`~json.JSONDecoder`.
            encoding: String encoding.
            unicode_errors: Controls how encoding errors are handled.
            limit: Maximum buffer size. Used in incremental serialization context.
            use_lines: If :data:`True` (the default), each ASCII lines is considered a JSON object.
            debug: If :data:`True`, add information to :exc:`.DeserializeError` via the ``error_info`` attribute.

        See Also:
            :ref:`standard-encodings` and :ref:`error-handlers`.

        """
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

        if limit <= 0:
            raise ValueError("limit must be a positive integer")

        self.__encoder = JSONEncoder(**dataclass_asdict(encoder_config), indent=None, separators=(",", ":"))
        self.__decoder = JSONDecoder(**dataclass_asdict(decoder_config))
        self.__decoder_error_cls = JSONDecodeError

        self.__encoding: str = encoding
        self.__unicode_errors: str = unicode_errors

        self.__limit: int = limit
        self.__use_lines: bool = bool(use_lines)

        self.__debug: bool = bool(debug)

    @final
    def serialize(self, packet: Any) -> bytes:
        """
        Returns the JSON representation of the Python object `packet`.

        Roughly equivalent to::

            def serialize(self, packet):
                return json.dumps(packet)

        Example:
            >>> s = JSONSerializer()
            >>> s.serialize({"key": [1, 2, 3], "data": None})
            b'{"key":[1,2,3],"data":null}'

        Parameters:
            packet: The Python object to serialize.

        Returns:
            a byte sequence.
        """
        return bytes(self.__encoder.encode(packet), self.__encoding, self.__unicode_errors)

    @final
    def incremental_serialize(self, packet: Any) -> Generator[bytes]:
        r"""
        Returns the JSON representation of the Python object `packet`.

        Example:
            >>> s = JSONSerializer()
            >>> b"".join(s.incremental_serialize({"key": [1, 2, 3], "data": None}))
            b'{"key":[1,2,3],"data":null}\n'

        Parameters:
            packet: The Python object to serialize.

        Yields:
            all the parts of the JSON :term:`packet`.
        """
        data = bytes(self.__encoder.encode(packet), self.__encoding, self.__unicode_errors)
        if self.__use_lines or not data.startswith(_OBJECT_START):
            data += b"\n"
        yield data

    @final
    def deserialize(self, data: bytes) -> Any:
        """
        Creates a Python object representing the raw JSON :term:`packet` from `data`.

        Roughly equivalent to::

            def deserialize(self, data):
                return json.loads(data)

        Example:
            >>> s = JSONSerializer()
            >>> s.deserialize(b'{"key":[1,2,3],"data":null}')
            {'key': [1, 2, 3], 'data': None}

        Parameters:
            data: The byte sequence to deserialize.

        Raises:
            DeserializeError: A :class:`UnicodeError` or :class:`~json.JSONDecodeError` have been raised.

        Returns:
            the deserialized Python object.
        """
        try:
            document: str = str(data, self.__encoding, self.__unicode_errors)
        except UnicodeError as exc:
            msg = f"Unicode decode error: {exc}"
            if self.debug:
                raise DeserializeError(msg, error_info={"data": data}) from exc
            raise DeserializeError(msg) from exc
        finally:
            del data
        try:
            packet: Any = self.__decoder.decode(document)
        except self.__decoder_error_cls as exc:
            msg = f"JSON decode error: {exc}"
            if self.debug:
                raise DeserializeError(
                    msg,
                    error_info={
                        "document": exc.doc,
                        "position": exc.pos,
                        "lineno": exc.lineno,
                        "colno": exc.colno,
                    },
                ) from exc
            raise DeserializeError(msg) from exc
        return packet

    @final
    def incremental_deserialize(self) -> Generator[None, bytes, tuple[Any, bytes]]:
        """
        Creates a Python object representing the raw JSON :term:`packet`.

        Example:
            >>> s = JSONSerializer(use_lines=False)
            >>> consumer = s.incremental_deserialize()
            >>> next(consumer)
            >>> consumer.send(b'{"key":[1,2,3]')
            >>> consumer.send(b',"data":null}{"something":"remaining"}')
            Traceback (most recent call last):
            ...
            StopIteration: ({'key': [1, 2, 3], 'data': None}, b'{"something":"remaining"}')

        Yields:
            :data:`None` until the whole :term:`packet` has been deserialized.

        Raises:
            LimitOverrunError: Reached buffer size limit.
            IncrementalDeserializeError: A :class:`UnicodeError` or :class:`~json.JSONDecodeError` have been raised.

        Returns:
            a tuple with the deserialized Python object and the unused trailing data.
        """
        complete_document: ReadableBuffer
        remaining_data: ReadableBuffer
        if self.__use_lines:
            reader = GeneratorStreamReader()
            complete_document = yield from reader.read_until(b"\n", limit=self.__limit, keep_end=False)
            remaining_data = reader.read_all()
            del reader
        else:
            complete_document, remaining_data = yield from _JSONParser.raw_parse(limit=self.__limit)

        packet: Any
        try:
            document: str = str(complete_document, self.__encoding, self.__unicode_errors)
        except UnicodeError as exc:
            msg = f"Unicode decode error: {exc}"
            if self.debug:
                raise IncrementalDeserializeError(
                    msg,
                    remaining_data=remaining_data,
                    error_info={"data": complete_document},
                ) from exc
            raise IncrementalDeserializeError(msg, remaining_data) from exc
        finally:
            del complete_document
        try:
            packet = self.__decoder.decode(document)
        except self.__decoder_error_cls as exc:
            msg = f"JSON decode error: {exc}"
            if self.debug:
                raise IncrementalDeserializeError(
                    msg,
                    remaining_data=remaining_data,
                    error_info={
                        "document": exc.doc,
                        "position": exc.pos,
                        "lineno": exc.lineno,
                        "colno": exc.colno,
                    },
                ) from exc
            raise IncrementalDeserializeError(msg, remaining_data) from exc
        return packet, bytes(remaining_data)

    @property
    @final
    def debug(self) -> bool:
        """
        The debug mode flag. Read-only attribute.
        """
        return self.__debug

    @property
    @final
    def buffer_limit(self) -> int:
        """
        Maximum buffer size. Read-only attribute.
        """
        return self.__limit


class _JSONParser:
    _QUOTE_BYTE: int = ord('"')
    _ESCAPE_BYTE: int = ord("\\")
    _ENCLOSURE_BYTES: dict[int, int] = {
        ord("{"): ord("}"),
        ord("["): ord("]"),
        ord('"'): ord('"'),
    }

    _NON_PRINTABLE: re.Pattern[bytes] = re.compile(rb"[^\x20-\x7E]", re.MULTILINE | re.DOTALL)
    _WHITESPACES: re.Pattern[bytes] = re.compile(rb"[ \t\n\r]*", re.MULTILINE | re.DOTALL)
    _JSON_FRAMES: dict[int, re.Pattern[bytes]] = {
        ord("{"): re.compile(rb'(?:\\.|[\{\}"])', re.MULTILINE | re.DOTALL),
        ord("["): re.compile(rb'(?:\\.|[\[\]"])', re.MULTILINE | re.DOTALL),
        ord('"'): re.compile(rb'(?:\\.|["])', re.MULTILINE | re.DOTALL),
    }

    @classmethod
    def raw_parse(
        cls,
        *,
        limit: int,
        _w: Callable[[bytes | bytearray, int], re.Match[bytes]] = _WHITESPACES.match,  # type: ignore[assignment]
        _np: Callable[[bytes | bytearray, int], re.Match[bytes] | None] = _NON_PRINTABLE.search,
    ) -> Generator[None, bytes, tuple[ReadableBuffer, ReadableBuffer]]:
        if limit <= 0:
            raise ValueError("limit must be a positive integer")

        append_to_buffer = cls.__append_to_buffer

        partial_document: bytes | bytearray
        start_idx: int

        partial_document = bytes((yield))
        while (start_idx := _w(partial_document, 0).end()) == len(partial_document):
            del partial_document
            partial_document = bytes((yield))

        end_idx: int = start_idx
        if (open_enclosure := partial_document[start_idx]) not in cls._ENCLOSURE_BYTES:
            while not (nprint_search := _np(partial_document, end_idx)):
                partial_document, end_idx = yield from append_to_buffer(partial_document, limit)

            end_idx = nprint_search.start()
            complete_document, partial_document_view = cls.__split_final_buffer(
                partial_document,
                start_idx=start_idx,
                end_idx=end_idx,
                limit=limit,
            )
            del partial_document
            if not complete_document:
                # If this condition is verified, decoder.decode() will most likely raise JSONDecodeError
                return partial_document_view, b""
            return complete_document, partial_document_view

        ESCAPE_BYTE = cls._ESCAPE_BYTE
        QUOTE_BYTE = cls._QUOTE_BYTE
        close_enclosure = cls._ENCLOSURE_BYTES[open_enclosure]
        token_finder = cls._JSON_FRAMES[open_enclosure].finditer
        enclosure_count: int = 1
        between_quotes: bool = open_enclosure == QUOTE_BYTE
        end_idx += 1
        while True:
            for enclosure_match in token_finder(partial_document, end_idx):
                byte = enclosure_match[0][0]
                if byte == QUOTE_BYTE:
                    between_quotes = not between_quotes
                elif between_quotes:
                    continue

                # Try first to match close_enclosure for frames using the same character for opening and closing (e.g. strings)
                if byte == close_enclosure:
                    enclosure_count -= 1
                elif byte == open_enclosure:  # pragma: no branch
                    enclosure_count += 1

                if not enclosure_count:  # 1st found is closed
                    end_idx = enclosure_match.end()
                    return cls.__split_final_buffer(partial_document, start_idx=start_idx, end_idx=end_idx, limit=limit)

            partial_document, end_idx = yield from append_to_buffer(partial_document, limit)
            while partial_document[end_idx - 1] == ESCAPE_BYTE:
                end_idx -= 1

    @staticmethod
    def __split_final_buffer(
        partial_document: bytes | bytearray,
        *,
        start_idx: int,
        end_idx: int,
        limit: int,
        _w: Callable[[bytes | bytearray, int], re.Match[bytes]] = _WHITESPACES.match,  # type: ignore[assignment]
    ) -> tuple[memoryview, memoryview]:
        if end_idx > limit:
            raise LimitOverrunError(
                "JSON object's end frame is found, but chunk is longer than limit",
                partial_document,
                end_idx,
            )
        end_idx = _w(partial_document, end_idx).end()
        partial_document_view = memoryview(partial_document)
        return partial_document_view[start_idx:end_idx], partial_document_view[end_idx:]

    @staticmethod
    def __append_to_buffer(partial_document: bytes | bytearray, limit: int) -> Generator[None, bytes, tuple[bytearray, int]]:
        end_idx = len(partial_document)
        if end_idx > limit:
            raise LimitOverrunError(
                "JSON object's end frame is not found, and chunk exceed the limit",
                partial_document,
                end_idx,
            )
        if not isinstance(partial_document, bytearray):
            partial_document = bytearray(partial_document)
        partial_document.extend((yield))
        return partial_document, end_idx
