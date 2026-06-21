from __future__ import annotations

import json
from typing import Any

from easynetwork.serializers.abc import AbstractPacketSerializer

type SentPacket = Any
type ReceivedPacket = Any


class MyJSONSerializer(AbstractPacketSerializer[SentPacket, ReceivedPacket]):
    def serialize(self, packet: SentPacket) -> bytes:
        document = json.dumps(packet)
        return document.encode()

    def deserialize(self, data: bytes) -> ReceivedPacket:
        document = data.decode()
        return json.loads(document)
