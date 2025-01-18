from __future__ import annotations

from easynetwork.clients.unix_datagram import UnixDatagramClient
from easynetwork.protocol import DatagramProtocol
from easynetwork.serializers import JSONSerializer


def main() -> None:
    protocol = DatagramProtocol(JSONSerializer())
    address = "/var/run/app/app.sock"

    with UnixDatagramClient(address, protocol) as client:
        print(f"Remote address: {client.get_peer_name()}")

        ...


if __name__ == "__main__":
    main()
