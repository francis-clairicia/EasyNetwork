from __future__ import annotations

import json
from collections.abc import Generator
from typing import TYPE_CHECKING, Any

from easynetwork.exceptions import DeserializeError, IncrementalDeserializeError
from easynetwork.serializers.abc import BufferedIncrementalPacketSerializer

if TYPE_CHECKING:
    from _typeshed import ReadableBuffer


class MyJSONSerializer(BufferedIncrementalPacketSerializer[Any, bytearray]):
    def __init__(self, *, ensure_ascii: bool = True) -> None:
        self._ensure_ascii: bool = ensure_ascii

        self._encoding: str
        if self._ensure_ascii:
            self._encoding = "ascii"
        else:
            self._encoding = "utf-8"

    def _dump(self, packet: Any) -> bytes:
        document = json.dumps(packet, ensure_ascii=self._ensure_ascii)
        return document.encode(self._encoding)

    def _load(self, data: bytes | bytearray) -> Any:
        document = data.decode(self._encoding)
        return json.loads(document)

    def serialize(self, packet: Any) -> bytes:
        return self._dump(packet)

    def deserialize(self, data: bytes) -> Any:
        try:
            return self._load(data)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise DeserializeError("JSON decode error") from exc

    def incremental_serialize(self, packet: Any) -> Generator[bytes, None, None]:
        yield self._dump(packet) + b"\r\n"

    def incremental_deserialize(self) -> Generator[None, bytes, tuple[Any, bytes]]:
        data = yield
        newline = b"\r\n"
        while (index := data.find(newline)) < 0:
            data += yield

        remainder = data[index + len(newline) :]
        data = data[:index]

        try:
            document = self._load(data)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise IncrementalDeserializeError("JSON decode error", remainder) from exc

        return document, remainder

    def create_deserializer_buffer(self, sizehint: int) -> bytearray:
        buffer_size: int = max(sizehint, 65536)
        return bytearray(buffer_size)

    def buffered_incremental_deserialize(
        self,
        buffer: bytearray,
    ) -> Generator[int | None, int, tuple[Any, ReadableBuffer]]:
        buffer_size = len(buffer)
        newline = b"\r\n"
        separator_length = len(newline)

        nb_written_bytes: int = (yield None)

        while (index := buffer.find(newline, 0, nb_written_bytes)) < 0:
            start_idx: int = nb_written_bytes
            if start_idx > buffer_size - separator_length:
                raise IncrementalDeserializeError("Too long line", remaining_data=b"")
            nb_written_bytes += yield start_idx

        remainder: bytearray = buffer[index + separator_length : nb_written_bytes]
        data: bytearray = buffer[:index]

        try:
            document = self._load(data)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise IncrementalDeserializeError("JSON decode error", remainder) from exc

        return document, remainder
