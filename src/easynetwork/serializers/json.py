# Copyright 2021-2024, Francis Clairicia-Rose-Claire-Josephine
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
import string
from collections import Counter
from collections.abc import Callable, Generator
from dataclasses import asdict as dataclass_asdict, dataclass
from typing import Any, final

from ..exceptions import DeserializeError, IncrementalDeserializeError, LimitOverrunError
from ..lowlevel._utils import iter_bytes
from ..lowlevel.constants import DEFAULT_SERIALIZER_LIMIT
from .abc import AbstractIncrementalPacketSerializer
from .tools import GeneratorStreamReader


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
        return self.__encoder.encode(packet).encode(self.__encoding, self.__unicode_errors)

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
        data = self.__encoder.encode(packet).encode(self.__encoding, self.__unicode_errors)
        if self.__use_lines or not data.startswith((b"{", b"[", b'"')):
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
        complete_document: bytes
        remaining_data: bytes
        if self.__use_lines:
            reader = GeneratorStreamReader()
            complete_document = yield from reader.read_until(b"\n", limit=self.__limit)
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
        return packet, remaining_data

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
    _JSON_VALUE_BYTES: frozenset[int] = frozenset(bytes(string.digits + string.ascii_letters + string.punctuation, "ascii"))
    _ESCAPE_BYTE: int = ord(b"\\")

    _whitespaces_match: Callable[[bytes, int], re.Match[bytes]] = re.compile(rb"[ \t\n\r]*", re.MULTILINE | re.DOTALL).match  # type: ignore[assignment]

    class _PlainValueError(Exception):
        pass

    @staticmethod
    def _escaped(partial_document_view: memoryview) -> bool:
        escaped = False
        _ESCAPE_BYTE = _JSONParser._ESCAPE_BYTE
        for byte in reversed(partial_document_view):
            if byte == _ESCAPE_BYTE:
                escaped = not escaped
            else:
                break
        return escaped

    @staticmethod
    def raw_parse(*, limit: int) -> Generator[None, bytes, tuple[bytes, bytes]]:
        if limit <= 0:
            raise ValueError("limit must be a positive integer")
        escaped = _JSONParser._escaped
        split_partial_document = _JSONParser._split_partial_document
        enclosure_counter: Counter[bytes] = Counter()
        partial_document: bytes = yield
        first_enclosure: bytes = b""
        try:
            offset: int = 0
            while True:
                with memoryview(partial_document) as partial_document_view:
                    for offset, char in enumerate(iter_bytes(partial_document_view[offset:]), start=offset):
                        match char:
                            case b'"' if not escaped(partial_document_view[:offset]):
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
                                partial_document = partial_document[offset:] if offset > 0 else partial_document
                                del char, offset
                                raise _JSONParser._PlainValueError
                            case _:  # JSON character, quickly go to next character
                                continue
                        assert len(enclosure_counter) > 0  # nosec assert_used
                        if not first_enclosure:
                            first_enclosure = next(iter(enclosure_counter))
                        if enclosure_counter[first_enclosure] <= 0:  # 1st found is closed
                            return split_partial_document(partial_document, offset + 1, limit)

                    # partial_document not complete
                    offset = partial_document_view.nbytes
                    if offset > limit:
                        raise LimitOverrunError(
                            "JSON object's end frame is not found, and chunk exceed the limit",
                            partial_document,
                            offset,
                        )

                # yield outside view scope
                partial_document += yield

        except _JSONParser._PlainValueError:
            pass

        # The document is a plain value (null, true, false, or a number)

        del enclosure_counter, first_enclosure

        _JSON_VALUE_BYTES = _JSONParser._JSON_VALUE_BYTES

        while (nprint_idx := next((idx for idx, byte in enumerate(partial_document) if byte not in _JSON_VALUE_BYTES), -1)) < 0:
            if len(partial_document) > limit:
                raise LimitOverrunError(
                    "JSON object's end frame is not found, and chunk exceed the limit",
                    partial_document,
                    len(partial_document),
                )
            partial_document += yield

        return split_partial_document(partial_document, nprint_idx, limit)

    @staticmethod
    def _split_partial_document(partial_document: bytes, consumed: int, limit: int) -> tuple[bytes, bytes]:
        if consumed > limit:
            raise LimitOverrunError(
                "JSON object's end frame is found, but chunk is longer than limit",
                partial_document,
                consumed,
            )
        consumed = _JSONParser._whitespaces_match(partial_document, consumed).end()
        if consumed == len(partial_document):
            # The following bytes are only spaces
            # Do not slice the document, the trailing spaces will be ignored by JSONDecoder
            return partial_document, b""
        complete_document, partial_document = partial_document[:consumed], partial_document[consumed:]
        if not complete_document:
            # If this condition is verified, decoder.decode() will most likely raise JSONDecodeError
            complete_document = partial_document
            partial_document = b""
        return complete_document, partial_document
