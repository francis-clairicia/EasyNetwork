from __future__ import annotations

from easynetwork.clients import TCPNetworkClient
from easynetwork.protocol import StreamProtocol
from easynetwork.serializers import PickleSerializer


def main() -> None:
    from easynetwork.serializers.wrapper import Base64EncoderSerializer

    # Reduce pickle size by adding pickler_optimize=True
    serializer = Base64EncoderSerializer(PickleSerializer(pickler_optimize=True), checksum=True)
    protocol = StreamProtocol(serializer)

    with TCPNetworkClient(("remote_address", 12345), protocol) as endpoint:
        endpoint.send_packet({"data": 42})

        ...
