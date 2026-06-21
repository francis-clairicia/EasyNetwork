from __future__ import annotations

from typing import Any

from easynetwork.protocol import StreamProtocol
from easynetwork.serializers import JSONSerializer

type SentPacket = Any
type ReceivedPacket = Any

json_protocol: StreamProtocol[SentPacket, ReceivedPacket] = StreamProtocol(JSONSerializer())
