from __future__ import annotations

from easynetwork.api_sync.client import UDPNetworkEndpoint
from easynetwork.exceptions import DatagramProtocolParseError

from ..basics.datagram_protocol_subclass import JSONDatagramProtocol


def main() -> None:
    protocol = JSONDatagramProtocol()

    with UDPNetworkEndpoint(protocol) as endpoint:
        endpoint.send_packet_to({"data": 42}, ("remote_address", 12345))

        ...

        try:
            received_packet, sender_address = endpoint.recv_packet_from()
        except DatagramProtocolParseError:
            print("The received data is invalid.")
        else:
            print(f"Received {received_packet!r} from {sender_address}.")
