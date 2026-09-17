from __future__ import annotations

from collections.abc import Generator

from easynetwork.servers.handlers import BlockingDatagramClient, BlockingDatagramRequestHandler


class Request:
    """Object representing the client request."""

    ...


class Response:
    """Object representing the response to send to the client."""

    ...


class MyRequestHandler(BlockingDatagramRequestHandler[Request, Response]):
    """
    The request handler class for our server.

    It is instantiated once to the server, and must
    override the handle() method to implement communication to the
    client.
    """

    def handle(
        self,
        client: BlockingDatagramClient[Response],
    ) -> Generator[None, Request]:
        # "client" a placeholder to have a stream-like API.
        # All the datagrams sent by this client are sent
        # through the "yield" statement.
        request: Request = yield

        # Do some stuff
        ...

        response = Response()

        # The corresponding call is server_socket.sendto(data, remote_address)
        client.send_packet(response)
