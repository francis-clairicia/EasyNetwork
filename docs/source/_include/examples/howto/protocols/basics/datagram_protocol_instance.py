from __future__ import annotations

from typing import Any, TypeAlias

from easynetwork.protocol import DatagramProtocol
from easynetwork.serializers import JSONSerializer

SentPacket: TypeAlias = Any
ReceivedPacket: TypeAlias = Any

json_protocol: DatagramProtocol[SentPacket, ReceivedPacket] = DatagramProtocol(JSONSerializer())
