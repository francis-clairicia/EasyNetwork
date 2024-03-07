from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any, TypeAlias

from easynetwork.exceptions import StreamProtocolParseError
from easynetwork.servers.handlers import AsyncStreamClient, AsyncStreamRequestHandler, INETClientAttribute

# These TypeAliases are there to help you understand
# where requests and responses are used
RequestType: TypeAlias = Any
ResponseType: TypeAlias = Any


class EchoRequestHandler(AsyncStreamRequestHandler[RequestType, ResponseType]):
    async def handle(
        self,
        client: AsyncStreamClient[ResponseType],
    ) -> AsyncGenerator[None, RequestType]:
        try:
            request: RequestType = yield  # A JSON request has been sent by this client
        except StreamProtocolParseError:
            # Invalid JSON data sent
            # This is an example of how you can answer to an invalid request
            await client.send_packet({"error": "Invalid JSON", "code": "parse_error"})
            return

        client_address = client.extra(INETClientAttribute.remote_address)
        print(f"{client_address.host} sent {request}")

        # As a good echo handler, the request is sent back to the client
        response: ResponseType = request
        await client.send_packet(response)
