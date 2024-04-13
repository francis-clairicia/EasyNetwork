from __future__ import annotations

import asyncio

from easynetwork.clients import AsyncTCPNetworkClient
from easynetwork.lowlevel.std_asyncio import AsyncIOBackend
from easynetwork.protocol import StreamProtocol
from easynetwork.serializers import JSONSerializer


async def main() -> None:
    protocol = StreamProtocol(JSONSerializer())
    address = ("localhost", 9000)
    backend = AsyncIOBackend()

    async with AsyncTCPNetworkClient(address, protocol, backend) as client:
        print(f"Remote address: {client.get_remote_address()}")

        ...


if __name__ == "__main__":
    asyncio.run(main())
