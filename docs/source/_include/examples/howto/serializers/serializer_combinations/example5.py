from __future__ import annotations

from easynetwork.clients import TCPNetworkClient
from easynetwork.protocol import StreamProtocol
from easynetwork.serializers import PickleSerializer


def main() -> None:
    from zlib import Z_BEST_COMPRESSION

    from easynetwork.serializers.wrapper import Base64EncoderSerializer, ZlibCompressorSerializer

    # Sign the checksum hash with a key known only to both sides of the pipe to verify the origin of the data.
    verification_key = b"very secret key"
    serializer = Base64EncoderSerializer(
        ZlibCompressorSerializer(PickleSerializer(pickler_optimize=True), compress_level=Z_BEST_COMPRESSION),
        checksum=verification_key,
    )
    protocol = StreamProtocol(serializer)

    with TCPNetworkClient(("remote_address", 12345), protocol) as endpoint:
        endpoint.send_packet({"data": 42})

        ...
