from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

from easynetwork.protocol import DatagramProtocol
from easynetwork.servers.async_unix_datagram import AsyncUnixDatagramServer
from easynetwork.servers.handlers import AsyncDatagramClient, AsyncDatagramRequestHandler


class Request: ...


class Response: ...


class MyRequestHandler(AsyncDatagramRequestHandler[Request, Response]):
    async def handle(
        self,
        client: AsyncDatagramClient[Response],
    ) -> AsyncGenerator[None, Request]:
        request: Request = yield

        ...

        await client.send_packet(Response())


# NOTE: The sent packet is "Response" and the received packet is "Request"
class ServerProtocol(DatagramProtocol[Response, Request]):
    def __init__(self) -> None: ...


async def main() -> None:
    path = "/var/run/app/app.sock"
    protocol = ServerProtocol()
    handler = MyRequestHandler()

    # Create the server, binding to /var/run/app/app.sock
    async with AsyncUnixDatagramServer(path, protocol, handler) as server:
        # Activate the server; this will keep running until you
        # interrupt the program with Ctrl-C
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
