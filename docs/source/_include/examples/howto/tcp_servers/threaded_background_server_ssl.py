from __future__ import annotations

import ssl
import threading
from collections.abc import Generator
from typing import Any

from easynetwork.clients import TCPNetworkClient
from easynetwork.protocol import StreamProtocol
from easynetwork.serializers import JSONSerializer
from easynetwork.servers import ThreadedTCPNetworkServer
from easynetwork.servers.handlers import BlockingStreamClient, BlockingStreamRequestHandler


class JSONProtocol(StreamProtocol[dict[str, Any], dict[str, Any]]):
    def __init__(self) -> None:
        super().__init__(JSONSerializer())


class MyRequestHandler(BlockingStreamRequestHandler[dict[str, Any], dict[str, Any]]):
    def handle(
        self,
        client: BlockingStreamClient[dict[str, Any]],
    ) -> Generator[None, dict[str, Any]]:
        request: dict[str, Any] = yield

        current_thread = threading.current_thread()

        client.send_packet({"thread": current_thread.name, "request": request})


def client(host: str, port: int, message: str) -> None:
    with TCPNetworkClient(
        (host, port),
        JSONProtocol(),
        ssl=True,
    ) as client:
        client.send_packet({"message": message})
        response = client.recv_packet()
        print(f"From server: {response}")


def main() -> None:
    host, port = "localhost", 9000
    protocol = JSONProtocol()
    handler = MyRequestHandler()

    ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ssl_context.load_cert_chain(
        "/path/to/ssl_cert.pem",
        "/path/to/ssl_key.pem",
    )
    server = ThreadedTCPNetworkServer(
        host,
        port,
        protocol,
        handler,
        ssl=ssl_context,
    )

    with server:
        is_up_event = threading.Event()
        server_thread = threading.Thread(target=server.serve_forever, kwargs={"is_up_event": is_up_event})
        server_thread.start()
        is_up_event.wait()

        print(f"Server loop running in thread: {server_thread.name}")

        client(host, port, "Hello world 1")
        client(host, port, "Hello world 2")
        client(host, port, "Hello world 3")

        server.shutdown()
        server_thread.join()


if __name__ == "__main__":
    main()
