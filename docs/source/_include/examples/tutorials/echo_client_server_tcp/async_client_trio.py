from __future__ import annotations

import sys

import trio

from easynetwork.clients import AsyncTCPNetworkClient

from json_protocol import JSONProtocol


async def main() -> None:
    host = "localhost"
    port = 9000
    protocol = JSONProtocol()

    # Connect to server
    async with AsyncTCPNetworkClient((host, port), protocol) as client:
        # Send data
        request = {"command-line arguments": sys.argv[1:]}
        await client.send_packet(request)

        # Receive data from the server and shut down
        response = await client.recv_packet()

    print(f"Sent:     {request}")
    print(f"Received: {response}")


if __name__ == "__main__":
    trio.run(main)
