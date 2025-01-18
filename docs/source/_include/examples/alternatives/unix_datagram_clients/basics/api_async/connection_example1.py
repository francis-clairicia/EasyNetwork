from __future__ import annotations

import asyncio

from easynetwork.clients.async_unix_datagram import AsyncUnixDatagramClient
from easynetwork.protocol import DatagramProtocol
from easynetwork.serializers import JSONSerializer


async def main() -> None:
    protocol = DatagramProtocol(JSONSerializer())
    address = "/var/run/app/app.sock"

    async with AsyncUnixDatagramClient(address, protocol) as client:
        print(f"Remote address: {client.get_peer_name()}")

        ...


if __name__ == "__main__":
    asyncio.run(main())
