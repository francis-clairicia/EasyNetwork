# Copyright (c) 2023, Francis Clairicia-Rose-Claire-Josephine
#
#
from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Any, TypeAlias

from easynetwork.api_async.server import AsyncBaseRequestHandler, AsyncClientInterface, StandaloneTCPNetworkServer
from easynetwork.exceptions import BaseProtocolParseError
from easynetwork.protocol import StreamProtocol
from easynetwork.serializers import JSONSerializer

# These TypeAliases are there to help you understand where requests and responses are used in the code
RequestType: TypeAlias = Any
ResponseType: TypeAlias = Any


class JSONProtocol(StreamProtocol[RequestType, ResponseType]):
    def __init__(self) -> None:
        super().__init__(JSONSerializer())


class EchoRequestHandler(AsyncBaseRequestHandler[RequestType, ResponseType]):
    async def handle(self, client: AsyncClientInterface[ResponseType]) -> AsyncGenerator[None, RequestType]:
        request: RequestType = yield  # A JSON request has been sent by this client

        print(f"{client.address} sent {request!r}")

        # As a good echo handler, the request is sent back to the client
        response: ResponseType = request
        await client.send_packet(response)

        # Leaving the generator will NOT close the connection, a new generator will be created afterwards.
        # You may manually close the connection if you want to:
        # await client.aclose()

    async def bad_request(self, client: AsyncClientInterface[ResponseType], exc: BaseProtocolParseError) -> None:
        # Invalid JSON data sent
        await client.send_packet({"data": {"error": "Invalid JSON", "code": "parse_error"}})


def main() -> None:
    host = None  # Bind on all interfaces
    # host = "" works too
    port = 9000

    logging.basicConfig(level=logging.INFO, format="[ %(levelname)s ] [ %(name)s ] %(message)s")
    with StandaloneTCPNetworkServer(host, port, JSONProtocol(), EchoRequestHandler()) as server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
