from __future__ import annotations

import json
from typing import Any

from easynetwork.exceptions import DeserializeError
from easynetwork.serializers.abc import AbstractPacketSerializer

type SentPacket = Any
type ReceivedPacket = Any


class MyJSONSerializer(AbstractPacketSerializer[SentPacket, ReceivedPacket]):
    def serialize(self, packet: SentPacket) -> bytes:
        document = json.dumps(packet)
        return document.encode()

    def deserialize(self, data: bytes) -> ReceivedPacket:
        try:
            document = data.decode()
            return json.loads(document)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise DeserializeError("JSON decode error") from exc
