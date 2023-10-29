from __future__ import annotations

from typing import Any, TypeAlias

from easynetwork.protocol import DatagramProtocol
from easynetwork.serializers import JSONSerializer

# Use of type aliases in order not to see two Any types without real meaning
# In our case, any serializable object will be sent/received
SentDataType: TypeAlias = Any
ReceivedDataType: TypeAlias = Any


class JSONDatagramProtocol(DatagramProtocol[SentDataType, ReceivedDataType]):
    def __init__(self) -> None:
        super().__init__(JSONSerializer())
