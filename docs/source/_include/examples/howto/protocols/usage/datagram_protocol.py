from __future__ import annotations

from easynetwork.api_sync.client import UDPNetworkEndpoint

from ..basics.datagram_protocol_subclass import JSONDatagramProtocol


def main() -> None:
    protocol = JSONDatagramProtocol()

    with UDPNetworkEndpoint(protocol) as endpoint:
        endpoint.send_packet_to({"data": 42}, ("remote_address", 12345))

        ...
