# Copyright (c) 2023, Francis Clairicia-Rose-Claire-Josephine
#
#
from __future__ import annotations

from typing import Any

from easynetwork.api_sync.client import TCPNetworkClient
from easynetwork.protocol import StreamProtocol
from easynetwork.serializers import JSONSerializer


class JSONProtocol(StreamProtocol[Any, Any]):
    def __init__(self) -> None:
        super().__init__(JSONSerializer())


def main() -> None:
    with TCPNetworkClient(("localhost", 9000), JSONProtocol()) as client:
        client.send_packet({"data": {"my_body": ["as json"]}})
        response = client.recv_packet()  # response will be a JSON
        print(response["data"])  # prints {'my_body': ['as json']}


if __name__ == "__main__":
    main()
