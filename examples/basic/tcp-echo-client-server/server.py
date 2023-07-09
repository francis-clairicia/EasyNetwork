# Copyright (c) 2023, Francis Clairicia-Rose-Claire-Josephine
#
#
from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Any

from easynetwork.api_async.server import AsyncBaseRequestHandler, AsyncClientInterface, StandaloneTCPNetworkServer
from easynetwork.exceptions import BaseProtocolParseError
from easynetwork.protocol import StreamProtocol
from easynetwork.serializers import JSONSerializer


class JSONProtocol(StreamProtocol[Any, Any]):
    def __init__(self) -> None:
        super().__init__(JSONSerializer())


class EchoRequestHandler(AsyncBaseRequestHandler[Any, Any]):
    async def handle(self, client: AsyncClientInterface[Any]) -> AsyncGenerator[None, Any]:
        request = yield  # A JSON request has been sent by this client

        print(f"{client.address} sent {request!r}")

        # As a good echo handler, the request is sent back to the client
        await client.send_packet(request)

    async def bad_request(self, client: AsyncClientInterface[Any], exc: BaseProtocolParseError) -> None:
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
