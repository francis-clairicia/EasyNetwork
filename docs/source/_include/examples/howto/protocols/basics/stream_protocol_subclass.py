from __future__ import annotations

from typing import Any

from easynetwork.protocol import StreamProtocol
from easynetwork.serializers import JSONSerializer

type SentPacket = Any
type ReceivedPacket = Any


class JSONStreamProtocol(StreamProtocol[SentPacket, ReceivedPacket]):
    def __init__(self) -> None:
        serializer = JSONSerializer()
        super().__init__(serializer)


json_protocol = JSONStreamProtocol()
