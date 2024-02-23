from __future__ import annotations

from easynetwork.clients import UDPNetworkClient
from easynetwork.exceptions import DatagramProtocolParseError

from ..basics.datagram_protocol_subclass import JSONDatagramProtocol


def main() -> None:
    protocol = JSONDatagramProtocol()

    with UDPNetworkClient(("remote_address", 12345), protocol) as endpoint:
        endpoint.send_packet({"data": 42})

        ...

        try:
            received_packet = endpoint.recv_packet()
        except DatagramProtocolParseError:
            print("The received data is invalid.")
        else:
            print(f"Received {received_packet!r} from {endpoint.get_remote_address()}.")
