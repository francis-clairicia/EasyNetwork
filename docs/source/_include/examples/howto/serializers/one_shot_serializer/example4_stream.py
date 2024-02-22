from __future__ import annotations

from easynetwork.clients import TCPNetworkClient
from easynetwork.protocol import StreamProtocol
from easynetwork.serializers.wrapper import Base64EncoderSerializer

from .example3 import MyJSONSerializer


def main() -> None:
    # Use of Base64EncoderSerializer as an incremental serializer wrapper
    serializer = Base64EncoderSerializer(MyJSONSerializer())
    protocol = StreamProtocol(serializer)

    with TCPNetworkClient(("remote_address", 12345), protocol) as endpoint:
        endpoint.send_packet({"data": 42})

        ...
