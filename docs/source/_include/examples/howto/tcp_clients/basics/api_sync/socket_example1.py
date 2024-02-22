from __future__ import annotations

import socket

from easynetwork.clients import TCPNetworkClient
from easynetwork.protocol import StreamProtocol
from easynetwork.serializers import JSONSerializer


def obtain_a_connected_socket() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    ...

    return sock


def main() -> None:
    protocol = StreamProtocol(JSONSerializer())
    sock = obtain_a_connected_socket()

    with TCPNetworkClient(sock, protocol) as client:
        print(f"Remote address: {client.get_remote_address()}")

        ...


if __name__ == "__main__":
    main()
