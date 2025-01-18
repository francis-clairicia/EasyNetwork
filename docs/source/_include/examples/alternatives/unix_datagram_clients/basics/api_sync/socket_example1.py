from __future__ import annotations

import socket
import tempfile

from easynetwork.clients.unix_datagram import UnixDatagramClient
from easynetwork.protocol import DatagramProtocol
from easynetwork.serializers import JSONSerializer


def obtain_a_connected_socket() -> socket.socket:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sock.bind(f"{tempfile.mkdtemp()}/local.sock")

    ...

    return sock


def main() -> None:
    protocol = DatagramProtocol(JSONSerializer())
    sock = obtain_a_connected_socket()

    with UnixDatagramClient(sock, protocol) as client:
        print(f"Remote address: {client.get_peer_name()}")

        ...


if __name__ == "__main__":
    main()
