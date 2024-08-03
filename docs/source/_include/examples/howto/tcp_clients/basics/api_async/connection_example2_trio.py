from __future__ import annotations

import trio

from easynetwork.clients import AsyncTCPNetworkClient
from easynetwork.protocol import StreamProtocol
from easynetwork.serializers import JSONSerializer


async def main() -> None:
    protocol = StreamProtocol(JSONSerializer())
    address = ("localhost", 9000)

    try:
        client = AsyncTCPNetworkClient(address, protocol)
        with trio.fail_after(30):
            await client.wait_connected()
    except trio.TooSlowError:
        print(f"Could not connect to {address} after 30 seconds")
        return

    async with client:
        print(f"Remote address: {client.get_remote_address()}")

        ...


if __name__ == "__main__":
    trio.run(main)
