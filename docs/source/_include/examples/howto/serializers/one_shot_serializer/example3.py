from __future__ import annotations

import json
from typing import Any

from easynetwork.exceptions import DeserializeError
from easynetwork.serializers.abc import AbstractPacketSerializer


class MyJSONSerializer(AbstractPacketSerializer[Any, Any]):
    def __init__(self, *, ensure_ascii: bool = True) -> None:
        self._ensure_ascii: bool = ensure_ascii

        self._encoding: str
        if self._ensure_ascii:
            self._encoding = "ascii"
        else:
            self._encoding = "utf-8"

    def serialize(self, packet: Any) -> bytes:
        document = json.dumps(packet, ensure_ascii=self._ensure_ascii)
        return document.encode(self._encoding)

    def deserialize(self, data: bytes) -> Any:
        try:
            document = data.decode(self._encoding)
            return json.loads(document)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise DeserializeError("JSON decode error") from exc
