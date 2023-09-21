from __future__ import annotations

from easynetwork.api_sync.client import UDPNetworkEndpoint
from easynetwork.protocol import DatagramProtocol

from .example3 import MyJSONSerializer


def main() -> None:
    serializer = MyJSONSerializer()
    protocol = DatagramProtocol(serializer)

    with UDPNetworkEndpoint(protocol) as endpoint:
        endpoint.send_packet_to({"data": 42}, ("remote_address", 12345))

        ...
