from __future__ import annotations

import asyncio
import socket

from easynetwork.clients import AsyncTCPNetworkClient
from easynetwork.protocol import StreamProtocol
from easynetwork.serializers import JSONSerializer


async def obtain_a_connected_socket() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    ...

    return sock


async def main() -> None:
    protocol = StreamProtocol(JSONSerializer())
    sock = await obtain_a_connected_socket()

    async with AsyncTCPNetworkClient(sock, protocol) as client:
        print(f"Remote address: {client.get_remote_address()}")

        ...


if __name__ == "__main__":
    asyncio.run(main())
