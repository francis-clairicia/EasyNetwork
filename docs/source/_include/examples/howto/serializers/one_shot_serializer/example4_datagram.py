from __future__ import annotations

from easynetwork.clients import UDPNetworkClient
from easynetwork.protocol import DatagramProtocol

from .example3 import MyJSONSerializer


def main() -> None:
    serializer = MyJSONSerializer()
    protocol = DatagramProtocol(serializer)

    with UDPNetworkClient(("remote_address", 12345), protocol) as endpoint:
        endpoint.send_packet({"data": 42})

        ...
