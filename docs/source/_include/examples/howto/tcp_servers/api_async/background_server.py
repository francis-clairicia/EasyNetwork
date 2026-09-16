from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

from easynetwork.clients import AsyncTCPNetworkClient
from easynetwork.protocol import StreamProtocol
from easynetwork.serializers import JSONSerializer
from easynetwork.servers import AsyncTCPNetworkServer
from easynetwork.servers.handlers import AsyncStreamClient, AsyncStreamRequestHandler


class JSONProtocol(StreamProtocol[dict[str, Any], dict[str, Any]]):
    def __init__(self) -> None:
        super().__init__(JSONSerializer())


class MyRequestHandler(AsyncStreamRequestHandler[dict[str, Any], dict[str, Any]]):
    async def handle(
        self,
        client: AsyncStreamClient[dict[str, Any]],
    ) -> AsyncGenerator[None, dict[str, Any]]:
        request: dict[str, Any] = yield

        current_task = asyncio.current_task()
        assert current_task is not None

        await client.send_packet({"task": current_task.get_name(), "request": request})


async def client(host: str, port: int, message: str) -> None:
    async with AsyncTCPNetworkClient(
        (host, port),
        JSONProtocol(),
    ) as client:
        await client.send_packet({"message": message})
        response = await client.recv_packet()
        print(f"From server: {response}")


async def main() -> None:
    host, port = "localhost", 9000
    protocol = JSONProtocol()
    handler = MyRequestHandler()

    server = AsyncTCPNetworkServer(
        host,
        port,
        protocol,
        handler,
    )

    async with server:
        is_up_event = asyncio.Event()
        server_task = asyncio.create_task(server.serve_forever(is_up_event=is_up_event))
        await is_up_event.wait()

        print(f"Server loop running in task: {server_task.get_name()}")

        await client(host, port, "Hello world 1")
        await client(host, port, "Hello world 2")
        await client(host, port, "Hello world 3")

        await server.shutdown()
        await server_task


if __name__ == "__main__":
    asyncio.run(main())
