from __future__ import annotations

from typing import Any

from easynetwork.api_async.client import AsyncTCPNetworkClient
from easynetwork.api_sync.client import TCPNetworkClient
from easynetwork.protocol import StreamProtocol
from easynetwork.serializers import JSONSerializer


def ssl_shared_lock_for_sync_client() -> None:
    remote_address = ("remote_address", 12345)
    protocol = StreamProtocol(JSONSerializer())

    def do_some_stuff(client: TCPNetworkClient[Any, Any]) -> None:
        pass

    # [start]
    client = TCPNetworkClient(
        remote_address,
        protocol,
        ssl=True,
        ssl_shared_lock=False,
    )
    do_some_stuff(client)


async def ssl_shared_lock_for_async_client() -> None:
    remote_address = ("remote_address", 12345)
    protocol = StreamProtocol(JSONSerializer())

    async def do_some_stuff(client: AsyncTCPNetworkClient[Any, Any]) -> None:
        pass

    # [start]
    client = AsyncTCPNetworkClient(
        remote_address,
        protocol,
        ssl=True,
        ssl_shared_lock=False,
    )
    await do_some_stuff(client)
