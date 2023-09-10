from __future__ import annotations

from easynetwork.api_sync.client import TCPNetworkClient

from ..basics.stream_protocol_subclass import JSONStreamProtocol


def main() -> None:
    protocol = JSONStreamProtocol()

    with TCPNetworkClient(("remote_address", 12345), protocol) as endpoint:
        endpoint.send_packet({"data": 42})

        ...
