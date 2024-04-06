from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncGenerator
from typing import Any

from easynetwork.clients import UDPNetworkClient
from easynetwork.protocol import DatagramProtocol
from easynetwork.serializers import JSONSerializer
from easynetwork.servers import StandaloneUDPNetworkServer
from easynetwork.servers.handlers import AsyncDatagramClient, AsyncDatagramRequestHandler
from easynetwork.servers.threads_helper import NetworkServerThread


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

        response = {
            "thread": threading.current_thread().name,
            "task": current_task.get_name(),
            "request": request,
        }
        await client.send_packet(response)


def client(host: str, port: int, message: str) -> None:
    with UDPNetworkClient((host, port), JSONProtocol()) as client:
        client.send_packet({"message": message})
        response = client.recv_packet()
        print(f"From server: {response}")


def main() -> None:
    host, port = "localhost", 9000
    protocol = JSONProtocol()
    handler = MyRequestHandler()

    server = StandaloneUDPNetworkServer(host, port, protocol, handler)

    with server:
        server_thread = NetworkServerThread(server)
        server_thread.start()

        print(f"Server loop running in thread: {server_thread.name}")

        client(host, port, "Hello world 1")
        client(host, port, "Hello world 2")
        client(host, port, "Hello world 3")

        server_thread.join()


if __name__ == "__main__":
    main()
