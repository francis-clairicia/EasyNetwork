from __future__ import annotations

import json
from typing import Any

from easynetwork.exceptions import DeserializeError
from easynetwork.serializers.abc import AbstractPacketSerializer


class MyJSONSerializer(AbstractPacketSerializer[Any, Any]):
    def serialize(self, packet: Any) -> bytes:
        document = json.dumps(packet)
        return document.encode()

    def deserialize(self, data: bytes) -> Any:
        try:
            document = data.decode()
            return json.loads(document)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise DeserializeError("JSON decode error") from exc
