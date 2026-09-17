from __future__ import annotations

from collections.abc import Generator

from easynetwork.protocol import DatagramProtocol
from easynetwork.servers.handlers import BlockingDatagramClient, BlockingDatagramRequestHandler
from easynetwork.servers.threaded_unix_datagram import ThreadedUnixDatagramServer


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
    path = "/var/run/app.sock"
    protocol = ServerProtocol()
    handler = MyRequestHandler()

    # Create the server, binding to /var/run/app.sock
    with ThreadedUnixDatagramServer(path, protocol, handler) as server:
        # Activate the server; this will keep running until you
        # interrupt the program with Ctrl-C
        server.serve_forever()


if __name__ == "__main__":
    main()
