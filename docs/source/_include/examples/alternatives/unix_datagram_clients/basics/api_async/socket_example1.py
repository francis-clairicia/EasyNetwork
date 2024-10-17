from __future__ import annotations

import asyncio
import socket
import tempfile

from easynetwork.clients.async_unix_datagram import AsyncUnixDatagramClient
from easynetwork.protocol import DatagramProtocol
from easynetwork.serializers import JSONSerializer


async def obtain_a_connected_socket() -> socket.socket:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sock.bind(f"{tempfile.mkdtemp()}/local.sock")

    ...

    return sock


async def main() -> None:
    protocol = DatagramProtocol(JSONSerializer())
    sock = await obtain_a_connected_socket()

    async with AsyncUnixDatagramClient(sock, protocol) as client:
        print(f"Remote address: {client.get_peer_name()}")

        ...


if __name__ == "__main__":
    asyncio.run(main())
