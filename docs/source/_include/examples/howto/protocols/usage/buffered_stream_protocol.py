from __future__ import annotations

from easynetwork.clients import TCPNetworkClient
from easynetwork.protocol import BufferedStreamProtocol
from easynetwork.serializers import StringLineSerializer


def main() -> None:
    serializer = StringLineSerializer()
    protocol = BufferedStreamProtocol(serializer)

    with TCPNetworkClient(("remote_address", 12345), protocol) as endpoint:
        endpoint.send_packet("Hello, world!")
