from __future__ import annotations

import asyncio

from easynetwork.api_async.client import AsyncTCPNetworkClient
from easynetwork.protocol import StreamProtocol
from easynetwork.serializers import JSONSerializer


async def main() -> None:
    protocol = StreamProtocol(JSONSerializer())
    address = ("localhost", 9000)

    try:
        async with asyncio.timeout(30):
            client = AsyncTCPNetworkClient(address, protocol)
            await client.wait_connected()
    except TimeoutError:
        print(f"Could not connect to {address} after 30 seconds")
        return

    async with client:
        print(f"Remote address: {client.get_remote_address()}")

        ...


if __name__ == "__main__":
    asyncio.run(main())
