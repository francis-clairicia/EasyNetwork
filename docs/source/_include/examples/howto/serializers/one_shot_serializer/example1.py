from __future__ import annotations

import json
from typing import Any

from easynetwork.serializers.abc import AbstractPacketSerializer


class MyJSONSerializer(AbstractPacketSerializer[Any, Any]):
    def serialize(self, packet: Any) -> bytes:
        document = json.dumps(packet)
        return document.encode()

    def deserialize(self, data: bytes) -> Any:
        document = data.decode()
        return json.loads(document)
