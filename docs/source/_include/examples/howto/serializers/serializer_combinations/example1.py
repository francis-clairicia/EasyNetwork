from __future__ import annotations

from easynetwork.clients import TCPNetworkClient
from easynetwork.protocol import StreamProtocol
from easynetwork.serializers import PickleSerializer


def main() -> None:
    from easynetwork.serializers.wrapper import Base64EncoderSerializer

    # Use of Base64EncoderSerializer as an incremental serializer wrapper
    # Each line (by default delimited with \r\n) is a base64 encoded pickle object.
    serializer = Base64EncoderSerializer(PickleSerializer())
    protocol = StreamProtocol(serializer)

    with TCPNetworkClient(("remote_address", 12345), protocol) as endpoint:
        # Sends b'gASVDQAAAAAAAAB9lIwEZGF0YZRLKnMu\r\n' over the TCP socket.
        endpoint.send_packet({"data": 42})

        ...
