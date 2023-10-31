from __future__ import annotations

import asyncio
import socket
from typing import Any

from easynetwork.api_async.client import AsyncUDPNetworkClient
from easynetwork.exceptions import DatagramProtocolParseError

###############
# Basic usage #
###############


async def send_packet_example1(client: AsyncUDPNetworkClient[Any, Any]) -> None:
    # [start]
    await client.send_packet({"data": 42})


async def recv_packet_example1(client: AsyncUDPNetworkClient[Any, Any]) -> None:
    # [start]
    packet = await client.recv_packet()
    print(f"Received packet: {packet!r}")


async def recv_packet_example2(client: AsyncUDPNetworkClient[Any, Any]) -> None:
    # [start]
    try:
        async with asyncio.timeout(30):
            packet = await client.recv_packet()
    except TimeoutError:
        print("Timed out")
    else:
        print(f"Received packet: {packet!r}")


async def recv_packet_example3(client: AsyncUDPNetworkClient[Any, Any]) -> None:
    # [start]
    try:
        async with asyncio.timeout(30):
            packet = await client.recv_packet()
    except DatagramProtocolParseError:
        print("Received something, but was not valid")
    except TimeoutError:
        print("Timed out")
    else:
        print(f"Received packet: {packet!r}")


async def recv_packet_example4(client: AsyncUDPNetworkClient[Any, Any]) -> None:
    # [start]
    all_packets = [p async for p in client.iter_received_packets()]


async def recv_packet_example5(client: AsyncUDPNetworkClient[Any, Any]) -> None:
    # [start]
    all_packets = [p async for p in client.iter_received_packets(timeout=1)]


##################
# Advanced usage #
##################


async def socket_proxy_example(client: AsyncUDPNetworkClient[Any, Any]) -> None:
    # [start]
    client.socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, True)
