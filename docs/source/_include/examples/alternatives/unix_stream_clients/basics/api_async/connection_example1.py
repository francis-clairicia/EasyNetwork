from __future__ import annotations

import asyncio

from easynetwork.clients.async_unix_stream import AsyncUnixStreamClient
from easynetwork.protocol import StreamProtocol
from easynetwork.serializers import JSONSerializer


async def main() -> None:
    protocol = StreamProtocol(JSONSerializer())
    address = "/var/run/app/app.sock"

    async with AsyncUnixStreamClient(address, protocol) as client:
        print(f"Remote address: {client.get_peer_name()}")

        ...


if __name__ == "__main__":
    asyncio.run(main())
