from __future__ import annotations

import json
from collections.abc import Generator
from typing import Any, TypeAlias

from easynetwork.exceptions import DeserializeError, IncrementalDeserializeError
from easynetwork.serializers.abc import AbstractIncrementalPacketSerializer

SentPacket: TypeAlias = Any
ReceivedPacket: TypeAlias = Any


class MyJSONSerializer(AbstractIncrementalPacketSerializer[SentPacket, ReceivedPacket]):
    def __init__(self, *, ensure_ascii: bool = True) -> None:
        self._encoding: str
        if ensure_ascii:
            self._encoding = "ascii"
        else:
            self._encoding = "utf-8"

    def _dump(self, packet: SentPacket) -> bytes:
        document = json.dumps(packet, ensure_ascii=(self._encoding == "ascii"))
        return document.encode(self._encoding)

    def _load(self, data: bytes) -> ReceivedPacket:
        document = data.decode(self._encoding)
        return json.loads(document)

    def serialize(self, packet: SentPacket) -> bytes:
        return self._dump(packet)

    def deserialize(self, data: bytes) -> ReceivedPacket:
        try:
            return self._load(data)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise DeserializeError("JSON decode error") from exc

    def incremental_serialize(self, packet: SentPacket) -> Generator[bytes]:
        yield self._dump(packet) + b"\r\n"

    def incremental_deserialize(self) -> Generator[None, bytes, tuple[ReceivedPacket, bytes]]:
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
