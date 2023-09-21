from __future__ import annotations

from typing import Any, TypeAlias

from easynetwork.protocol import StreamProtocol
from easynetwork.serializers import JSONSerializer

SentPacket: TypeAlias = Any
ReceivedPacket: TypeAlias = Any

json_protocol: StreamProtocol[SentPacket, ReceivedPacket] = StreamProtocol(JSONSerializer())
