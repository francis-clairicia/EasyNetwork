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
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except* KeyboardInterrupt:
        pass
