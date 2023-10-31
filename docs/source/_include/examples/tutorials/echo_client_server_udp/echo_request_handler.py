from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any, TypeAlias

from easynetwork.api_async.server import AsyncDatagramClient, AsyncDatagramRequestHandler, INETClientAttribute
from easynetwork.exceptions import DatagramProtocolParseError

RequestType: TypeAlias = Any
ResponseType: TypeAlias = Any


class EchoRequestHandler(AsyncDatagramRequestHandler[RequestType, ResponseType]):
    async def handle(
        self,
        client: AsyncDatagramClient[ResponseType],
    ) -> AsyncGenerator[None, RequestType]:
        try:
            request: RequestType = yield
        except DatagramProtocolParseError:
            await client.send_packet({"error": "Invalid JSON", "code": "parse_error"})
            return

        client_address = client.extra(INETClientAttribute.remote_address)
        print(f"{client_address.host} sent {request}")

        response: ResponseType = request
        await client.send_packet(response)
