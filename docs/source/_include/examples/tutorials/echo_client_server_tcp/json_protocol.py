from __future__ import annotations

from typing import Any

from easynetwork.protocol import StreamProtocol
from easynetwork.serializers import JSONSerializer

# Use of type aliases in order not to see two Any types without real meaning
# In our case, any serializable object will be sent/received
type SentDataType = Any
type ReceivedDataType = Any


class JSONProtocol(StreamProtocol[SentDataType, ReceivedDataType]):
    def __init__(self) -> None:
        super().__init__(JSONSerializer())
