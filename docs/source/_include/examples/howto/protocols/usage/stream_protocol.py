from __future__ import annotations

from easynetwork.clients import TCPNetworkClient
from easynetwork.exceptions import StreamProtocolParseError

from ..basics.stream_protocol_subclass import JSONStreamProtocol


def main() -> None:
    protocol = JSONStreamProtocol()

    with TCPNetworkClient(("remote_address", 12345), protocol) as endpoint:
        endpoint.send_packet({"data": 42})

        ...

        try:
            received_packet = endpoint.recv_packet()
        except StreamProtocolParseError:
            print("The received data is invalid.")
        else:
            print(f"Received {received_packet!r} from {endpoint.get_remote_address()}.")
