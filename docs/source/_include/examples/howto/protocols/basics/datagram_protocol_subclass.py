from __future__ import annotations

from typing import Any

from easynetwork.protocol import DatagramProtocol
from easynetwork.serializers import JSONSerializer

type SentPacket = Any
type ReceivedPacket = Any


class JSONDatagramProtocol(DatagramProtocol[SentPacket, ReceivedPacket]):
    def __init__(self) -> None:
        serializer = JSONSerializer()
        super().__init__(serializer)


json_protocol = JSONDatagramProtocol()
