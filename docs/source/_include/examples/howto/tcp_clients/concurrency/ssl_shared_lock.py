from __future__ import annotations

from easynetwork.clients import AsyncTCPNetworkClient, TCPNetworkClient
from easynetwork.lowlevel.std_asyncio import AsyncIOBackend
from easynetwork.protocol import StreamProtocol
from easynetwork.serializers import JSONSerializer


def ssl_shared_lock_for_sync_client() -> None:
    remote_address = ("remote_address", 12345)
    protocol = StreamProtocol(JSONSerializer())

    # [start]
    client = TCPNetworkClient(
        remote_address,
        protocol,
        ssl=True,
        ssl_shared_lock=False,
    )


async def ssl_shared_lock_for_async_client() -> None:
    remote_address = ("remote_address", 12345)
    protocol = StreamProtocol(JSONSerializer())
    backend = AsyncIOBackend()

    # [start]
    client = AsyncTCPNetworkClient(
        remote_address,
        protocol,
        backend,
        ssl=True,
        ssl_shared_lock=False,
    )
