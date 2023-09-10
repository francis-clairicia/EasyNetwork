from __future__ import annotations

from typing import Any, TypeAlias

from easynetwork.protocol import StreamProtocol
from easynetwork.serializers import JSONSerializer

SentPacket: TypeAlias = Any
ReceivedPacket: TypeAlias = Any


class JSONStreamProtocol(StreamProtocol[SentPacket, ReceivedPacket]):
    def __init__(self) -> None:
        serializer = JSONSerializer()
        super().__init__(serializer)


json_protocol = JSONStreamProtocol()
