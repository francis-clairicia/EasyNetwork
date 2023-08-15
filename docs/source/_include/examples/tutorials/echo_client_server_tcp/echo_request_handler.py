from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any, TypeAlias

from easynetwork.api_async.server import AsyncStreamClient, AsyncStreamRequestHandler
from easynetwork.exceptions import StreamProtocolParseError

# These TypeAliases are there to help you understand
# where requests and responses are used
RequestType: TypeAlias = Any
ResponseType: TypeAlias = Any


class EchoRequestHandler(AsyncStreamRequestHandler[RequestType, ResponseType]):
    async def handle(
        self,
        client: AsyncStreamClient[ResponseType],
    ) -> AsyncGenerator[None, RequestType]:
        request: RequestType = yield  # A JSON request has been sent by this client

        print(f"{client.address.host} sent {request}")

        # As a good echo handler, the request is sent back to the client
        response: ResponseType = request
        await client.send_packet(response)

    async def bad_request(
        self,
        client: AsyncStreamClient[ResponseType],
        exc: StreamProtocolParseError,
    ) -> None:
        # Invalid JSON data sent
        # This is an example of how you can answer to an invalid request
        await client.send_packet({"error": "Invalid JSON", "code": "parse_error"})
