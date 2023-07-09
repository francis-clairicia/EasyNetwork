# Copyright (c) 2023, Francis Clairicia-Rose-Claire-Josephine
#
#
# Copyright (c) 2023, Francis Clairicia-Rose-Claire-Josephine
#
#
from __future__ import annotations

import asyncio
from typing import Any

from easynetwork.api_async.client import AsyncTCPNetworkClient
from easynetwork.protocol import StreamProtocol
from easynetwork.serializers import JSONSerializer


class JSONProtocol(StreamProtocol[Any, Any]):
    def __init__(self) -> None:
        super().__init__(JSONSerializer())


async def main() -> None:
    async with AsyncTCPNetworkClient(("localhost", 9000), JSONProtocol()) as client:
        await client.send_packet({"data": {"my_body": ["as json"]}})
        response = await client.recv_packet()  # response will be a JSON
        print(response["data"])  # prints {'my_body': ['as json']}


if __name__ == "__main__":
    asyncio.run(main())
