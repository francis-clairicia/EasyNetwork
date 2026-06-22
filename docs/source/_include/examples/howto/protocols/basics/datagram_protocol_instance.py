from __future__ import annotations

from typing import Any

from easynetwork.protocol import DatagramProtocol
from easynetwork.serializers import JSONSerializer

type SentPacket = Any
type ReceivedPacket = Any

json_protocol: DatagramProtocol[SentPacket, ReceivedPacket] = DatagramProtocol(JSONSerializer())
