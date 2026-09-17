from __future__ import annotations

from collections.abc import Generator

from easynetwork.servers.handlers import BlockingStreamClient, BlockingStreamRequestHandler


class Request:
    """Object representing the client request."""

    ...


class Response:
    """Object representing the response to send to the client."""

    ...


class MyRequestHandler(BlockingStreamRequestHandler[Request, Response]):
    """
    The request handler class for our server.

    It is instantiated once to the server, and must
    override the handle() method to implement communication to the
    client.
    """

    def handle(
        self,
        client: BlockingStreamClient[Response],
    ) -> Generator[None, Request]:
        # "client" is the write stream of the connection to the remote host.
        # The read stream is covered by the server and the incoming
        # request is sent through the "yield" statement.
        request: Request = yield

        # Do some stuff
        ...

        response = Response()

        client.send_packet(response)
