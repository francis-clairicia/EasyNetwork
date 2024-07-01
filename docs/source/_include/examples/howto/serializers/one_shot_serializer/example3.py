from __future__ import annotations

import json
from typing import Any, TypeAlias

from easynetwork.exceptions import DeserializeError
from easynetwork.serializers.abc import AbstractPacketSerializer

SentPacket: TypeAlias = Any
ReceivedPacket: TypeAlias = Any


class MyJSONSerializer(AbstractPacketSerializer[SentPacket, ReceivedPacket]):
    def __init__(self, *, ensure_ascii: bool = True) -> None:
        self._encoding: str
        if ensure_ascii:
            self._encoding = "ascii"
        else:
            self._encoding = "utf-8"

    def serialize(self, packet: SentPacket) -> bytes:
        document = json.dumps(packet, ensure_ascii=(self._encoding == "ascii"))
        return document.encode(self._encoding)

    def deserialize(self, data: bytes) -> ReceivedPacket:
        try:
            document = data.decode(self._encoding)
            return json.loads(document)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise DeserializeError("JSON decode error") from exc
