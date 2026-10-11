from __future__ import annotations

from collections.abc import Generator

from easynetwork.protocol import DatagramProtocol
from easynetwork.servers import ThreadedUDPNetworkServer
from easynetwork.servers.handlers import BlockingDatagramClient, BlockingDatagramRequestHandler


class Request: ...


class Response: ...


class MyRequestHandler(BlockingDatagramRequestHandler[Request, Response]):
    def handle(
        self,
        client: BlockingDatagramClient[Response],
    ) -> Generator[None, Request]:
        request: Request = yield

        ...

        client.send_packet(Response())


# NOTE: The sent packet is "Response" and the received packet is "Request"
class ServerProtocol(DatagramProtocol[Response, Request]):
    def __init__(self) -> None: ...


def main() -> None:
    host, port = "localhost", 9000
    protocol = ServerProtocol()
    handler = MyRequestHandler()

    # Create the server, binding to localhost on port 9000
    with ThreadedUDPNetworkServer(host, port, protocol, handler) as server:
        # Activate the server; this will keep running until you
        # interrupt the program with Ctrl-C
        server.serve_forever()


if __name__ == "__main__":
    main()
