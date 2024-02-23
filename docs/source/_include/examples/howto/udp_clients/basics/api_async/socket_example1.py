from __future__ import annotations

import asyncio
import socket

from easynetwork.clients import AsyncUDPNetworkClient
from easynetwork.protocol import DatagramProtocol
from easynetwork.serializers import JSONSerializer


async def obtain_a_connected_socket() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    ...

    return sock


async def main() -> None:
    protocol = DatagramProtocol(JSONSerializer())
    sock = await obtain_a_connected_socket()

    async with AsyncUDPNetworkClient(sock, protocol) as client:
        print(f"Remote address: {client.get_remote_address()}")

        ...


if __name__ == "__main__":
    asyncio.run(main())
