from __future__ import annotations

import socket

from easynetwork.clients.unix_stream import UnixStreamClient
from easynetwork.protocol import StreamProtocol
from easynetwork.serializers import JSONSerializer


def obtain_a_connected_socket() -> socket.socket:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

    ...

    return sock


def main() -> None:
    protocol = StreamProtocol(JSONSerializer())
    sock = obtain_a_connected_socket()

    with UnixStreamClient(sock, protocol) as client:
        print(f"Remote address: {client.get_peer_name()}")

        ...


if __name__ == "__main__":
    main()
