from __future__ import annotations

from easynetwork.clients import UDPNetworkClient
from easynetwork.protocol import DatagramProtocol
from easynetwork.serializers import JSONSerializer


def main() -> None:
    protocol = DatagramProtocol(JSONSerializer())
    address = ("127.0.0.1", 9000)

    with UDPNetworkClient(address, protocol) as client:
        print(f"Remote address: {client.get_remote_address()}")

        ...


if __name__ == "__main__":
    main()
