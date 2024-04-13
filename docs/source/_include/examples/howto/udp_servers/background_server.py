from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

from easynetwork.clients import AsyncUDPNetworkClient
from easynetwork.lowlevel.std_asyncio import AsyncIOBackend
from easynetwork.protocol import DatagramProtocol
from easynetwork.serializers import JSONSerializer
from easynetwork.servers import AsyncUDPNetworkServer
from easynetwork.servers.handlers import AsyncDatagramClient, AsyncDatagramRequestHandler


class JSONProtocol(DatagramProtocol[dict[str, Any], dict[str, Any]]):
    def __init__(self) -> None:
        super().__init__(JSONSerializer())


class MyRequestHandler(AsyncDatagramRequestHandler[dict[str, Any], dict[str, Any]]):
    async def handle(
        self,
        client: AsyncDatagramClient[dict[str, Any]],
    ) -> AsyncGenerator[None, dict[str, Any]]:
        request: dict[str, Any] = yield

        current_task = asyncio.current_task()
        assert current_task is not None

        await client.send_packet({"task": current_task.get_name(), "request": request})


async def client(host: str, port: int, message: str, backend: AsyncIOBackend) -> None:
    async with AsyncUDPNetworkClient((host, port), JSONProtocol(), backend) as client:
        await client.send_packet({"message": message})
        response = await client.recv_packet()
        print(f"From server: {response}")


async def main() -> None:
    host, port = "localhost", 9000
    protocol = JSONProtocol()
    handler = MyRequestHandler()
    backend = AsyncIOBackend()

    server = AsyncUDPNetworkServer(
        host,
        port,
        protocol,
        handler,
        backend,
    )

    async with server:
        is_up_event = asyncio.Event()
        server_task = asyncio.create_task(server.serve_forever(is_up_event=is_up_event))
        await is_up_event.wait()

        print(f"Server loop running in task: {server_task.get_name()}")

        await client(host, port, "Hello world 1", backend)
        await client(host, port, "Hello world 2", backend)
        await client(host, port, "Hello world 3", backend)

        await server.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
