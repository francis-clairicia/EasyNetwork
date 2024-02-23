from __future__ import annotations

import socket

from easynetwork.clients import UDPNetworkClient
from easynetwork.protocol import DatagramProtocol
from easynetwork.serializers import JSONSerializer


def obtain_a_connected_socket() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    ...

    return sock


def main() -> None:
    protocol = DatagramProtocol(JSONSerializer())
    sock = obtain_a_connected_socket()

    with UDPNetworkClient(sock, protocol) as client:
        print(f"Remote address: {client.get_remote_address()}")

        ...


if __name__ == "__main__":
    main()
