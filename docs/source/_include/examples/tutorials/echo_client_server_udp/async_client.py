from __future__ import annotations

import asyncio
import sys

from easynetwork.clients import AsyncUDPNetworkClient
from easynetwork.lowlevel.std_asyncio import AsyncIOBackend

from json_protocol import JSONDatagramProtocol


async def main() -> None:
    host = "localhost"
    port = 9000
    protocol = JSONDatagramProtocol()
    backend = AsyncIOBackend()

    # Connect to server
    async with AsyncUDPNetworkClient((host, port), protocol, backend) as client:
        # Send data
        request = {"command-line arguments": sys.argv[1:]}
        await client.send_packet(request)

        # Receive data from the server and shut down
        response = await client.recv_packet()

    print(f"Sent:     {request}")
    print(f"Received: {response}")


if __name__ == "__main__":
    asyncio.run(main())
