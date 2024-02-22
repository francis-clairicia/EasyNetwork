from __future__ import annotations

import asyncio

from easynetwork.servers import AsyncUDPNetworkServer

from echo_request_handler import EchoRequestHandler
from json_protocol import JSONDatagramProtocol


async def main() -> None:
    host = None
    port = 9000
    protocol = JSONDatagramProtocol()
    handler = EchoRequestHandler()

    async with AsyncUDPNetworkServer(host, port, protocol, handler) as server:
        try:
            await server.serve_forever()
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    asyncio.run(main())
