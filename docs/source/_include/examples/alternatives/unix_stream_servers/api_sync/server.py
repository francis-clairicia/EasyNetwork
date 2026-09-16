from __future__ import annotations

from collections.abc import Generator

from easynetwork.protocol import StreamProtocol
from easynetwork.servers.handlers import BlockingStreamClient, BlockingStreamRequestHandler
from easynetwork.servers.threaded_unix_stream import ThreadedUnixStreamServer


class Request: ...


class Response: ...


class MyRequestHandler(BlockingStreamRequestHandler[Request, Response]):
    def handle(
        self,
        client: BlockingStreamClient[Response],
    ) -> Generator[None, Request]:
        request: Request = yield

        ...

        client.send_packet(Response())


# NOTE: The sent packet is "Response" and the received packet is "Request"
class ServerProtocol(StreamProtocol[Response, Request]):
    def __init__(self) -> None: ...


def main() -> None:
    path = "/var/run/app/app.sock"
    protocol = ServerProtocol()
    handler = MyRequestHandler()

    # Create the server, binding to /var/run/app/app.sock
    with ThreadedUnixStreamServer(path, protocol, handler) as server:
        # Activate the server; this will keep running until you
        # interrupt the program with Ctrl-C
        server.serve_forever()


if __name__ == "__main__":
    main()
