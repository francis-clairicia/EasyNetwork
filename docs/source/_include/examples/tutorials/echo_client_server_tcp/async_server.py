from __future__ import annotations

import asyncio

from easynetwork.servers import AsyncTCPNetworkServer

from echo_request_handler import EchoRequestHandler
from json_protocol import JSONProtocol


async def main() -> None:
    host = None
    port = 9000
    protocol = JSONProtocol()
    handler = EchoRequestHandler()

    async with AsyncTCPNetworkServer(host, port, protocol, handler) as server:
        try:
            await server.serve_forever()
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    asyncio.run(main())
