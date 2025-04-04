from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

from easynetwork.protocol import StreamProtocol
from easynetwork.servers.async_unix_stream import AsyncUnixStreamServer
from easynetwork.servers.handlers import AsyncStreamClient, AsyncStreamRequestHandler


class Request: ...


class Response: ...


class MyRequestHandler(AsyncStreamRequestHandler[Request, Response]):
    async def handle(
        self,
        client: AsyncStreamClient[Response],
    ) -> AsyncGenerator[None, Request]:
        request: Request = yield

        ...

        await client.send_packet(Response())


# NOTE: The sent packet is "Response" and the received packet is "Request"
class ServerProtocol(StreamProtocol[Response, Request]):
    def __init__(self) -> None: ...


async def main() -> None:
    path = "/var/run/app/app.sock"
    protocol = ServerProtocol()
    handler = MyRequestHandler()

    # Create the server, binding to /var/run/app/app.sock
    async with AsyncUnixStreamServer(path, protocol, handler) as server:
        # Activate the server; this will keep running until you
        # interrupt the program with Ctrl-C
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
