from __future__ import annotations

from easynetwork.clients import TCPNetworkClient
from easynetwork.protocol import StreamProtocol
from easynetwork.serializers import PickleSerializer


def main() -> None:
    from easynetwork.serializers.wrapper import Base64EncoderSerializer

    # Add checksum parameter to append a unique hash to verify data integrity
    serializer = Base64EncoderSerializer(PickleSerializer(), checksum=True)
    protocol = StreamProtocol(serializer)

    with TCPNetworkClient(("remote_address", 12345), protocol) as endpoint:
        endpoint.send_packet({"data": 42})

        ...
