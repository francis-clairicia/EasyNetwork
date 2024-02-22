from __future__ import annotations

from easynetwork.clients import TCPNetworkClient
from easynetwork.protocol import StreamProtocol
from easynetwork.serializers import JSONSerializer


def main() -> None:
    protocol = StreamProtocol(JSONSerializer())
    address = ("localhost", 9000)

    try:
        client = TCPNetworkClient(address, protocol, connect_timeout=30)
    except TimeoutError:
        print(f"Could not connect to {address} after 30 seconds")
        return

    with client:
        print(f"Remote address: {client.get_remote_address()}")

        ...


if __name__ == "__main__":
    main()
