from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any, TypeAlias

from easynetwork.api_async.server import AsyncBaseRequestHandler, AsyncClientInterface, StandaloneTCPNetworkServer
from easynetwork.exceptions import BaseProtocolParseError

from json_protocol import JSONProtocol

# These TypeAliases are there to help you understand where requests and responses are used
RequestType: TypeAlias = Any
ResponseType: TypeAlias = Any


class EchoRequestHandler(AsyncBaseRequestHandler[RequestType, ResponseType]):
    async def handle(self, client: AsyncClientInterface[ResponseType]) -> AsyncGenerator[None, RequestType]:
        request: RequestType = yield  # A JSON request has been sent by this client

        # As a good echo handler, the request is sent back to the client
        response: ResponseType = request
        await client.send_packet(response)

    async def bad_request(self, client: AsyncClientInterface[ResponseType], exc: BaseProtocolParseError) -> None:
        # Invalid JSON data sent
        await client.send_packet({"data": {"error": "Invalid JSON", "code": "parse_error"}})


def main() -> None:
    host = None
    port = 9000

    with StandaloneTCPNetworkServer(host, port, JSONProtocol(), EchoRequestHandler()) as server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
