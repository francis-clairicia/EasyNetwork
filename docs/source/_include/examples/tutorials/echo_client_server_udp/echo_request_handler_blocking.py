from __future__ import annotations

from collections.abc import Generator
from typing import Any

from easynetwork.exceptions import DatagramProtocolParseError
from easynetwork.servers.handlers import BlockingDatagramClient, BlockingDatagramRequestHandler, INETClientAttribute

type RequestType = Any
type ResponseType = Any


class EchoRequestHandler(BlockingDatagramRequestHandler[RequestType, ResponseType]):
    def handle(
        self,
        client: BlockingDatagramClient[ResponseType],
    ) -> Generator[None, RequestType]:
        try:
            request: RequestType = yield
        except DatagramProtocolParseError:
            client.send_packet({"error": "Invalid JSON", "code": "parse_error"})
            return

        client_address = client.extra(INETClientAttribute.remote_address)
        print(f"{client_address.host} sent {request}")

        response: ResponseType = request
        client.send_packet(response)
