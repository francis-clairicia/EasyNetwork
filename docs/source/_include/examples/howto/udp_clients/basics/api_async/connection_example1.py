from __future__ import annotations

import asyncio

from easynetwork.clients import AsyncUDPNetworkClient
from easynetwork.protocol import DatagramProtocol
from easynetwork.serializers import JSONSerializer


async def main() -> None:
    protocol = DatagramProtocol(JSONSerializer())
    address = ("localhost", 9000)

    async with AsyncUDPNetworkClient(address, protocol) as client:
        print(f"Remote address: {client.get_remote_address()}")

        ...


if __name__ == "__main__":
    asyncio.run(main())
