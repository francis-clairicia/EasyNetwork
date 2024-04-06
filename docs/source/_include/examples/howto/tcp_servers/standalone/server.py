from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack
from typing import Any

from easynetwork.protocol import StreamProtocol
from easynetwork.serializers import JSONSerializer
from easynetwork.servers import StandaloneTCPNetworkServer
from easynetwork.servers.handlers import AsyncStreamClient, AsyncStreamRequestHandler


class JSONProtocol(StreamProtocol[dict[str, Any], dict[str, Any]]):
    def __init__(self) -> None:
        super().__init__(JSONSerializer())


class MyRequestHandler(AsyncStreamRequestHandler[dict[str, Any], dict[str, Any]]):
    async def service_init(self, exit_stack: AsyncExitStack, server: Any) -> None:
        # StandaloneTCPNetworkServer wraps an AsyncTCPNetworkServer instance.
        # Therefore, "server" is still asynchronous.

        from easynetwork.servers import AsyncTCPNetworkServer

        assert isinstance(server, AsyncTCPNetworkServer)

    async def handle(
        self,
        client: AsyncStreamClient[dict[str, Any]],
    ) -> AsyncGenerator[None, dict[str, Any]]:
        request: dict[str, Any] = yield

        current_task = asyncio.current_task()
        assert current_task is not None

        response = {"task": current_task.get_name(), "request": request}
        await client.send_packet(response)


def main() -> None:
    host, port = "localhost", 9000
    protocol = JSONProtocol()
    handler = MyRequestHandler()

    # All the parameters are the same as AsyncTCPNetworkServer.
    server = StandaloneTCPNetworkServer(host, port, protocol, handler)

    with server:
        server.serve_forever()


if __name__ == "__main__":
    main()
