from __future__ import annotations

import asyncio
import socket
from typing import Any

import trio

from easynetwork.clients import AsyncTCPNetworkClient
from easynetwork.exceptions import StreamProtocolParseError
from easynetwork.protocol import StreamProtocol
from easynetwork.serializers import JSONSerializer

###############
# Basic usage #
###############


async def send_packet_example1(client: AsyncTCPNetworkClient[Any, Any]) -> None:
    # [start]
    await client.send_packet({"data": 42})


async def recv_packet_example1(client: AsyncTCPNetworkClient[Any, Any]) -> None:
    # [start]
    packet = await client.recv_packet()
    print(f"Received packet: {packet!r}")


async def recv_packet_example2_asyncio(client: AsyncTCPNetworkClient[Any, Any]) -> None:
    # [start]
    try:
        async with asyncio.timeout(30):
            packet = await client.recv_packet()
    except TimeoutError:
        print("Timed out")
    else:
        print(f"Received packet: {packet!r}")


async def recv_packet_example2_trio(client: AsyncTCPNetworkClient[Any, Any]) -> None:
    # [start]
    try:
        with trio.fail_after(30):
            packet = await client.recv_packet()
    except trio.TooSlowError:
        print("Timed out")
    else:
        print(f"Received packet: {packet!r}")


async def recv_packet_example2_backend_api(client: AsyncTCPNetworkClient[Any, Any]) -> None:
    # [start]
    try:
        with client.backend().timeout(30):
            packet = await client.recv_packet()
    except TimeoutError:
        print("Timed out")
    else:
        print(f"Received packet: {packet!r}")


async def recv_packet_example3_asyncio(client: AsyncTCPNetworkClient[Any, Any]) -> None:
    # [start]
    try:
        async with asyncio.timeout(30):
            packet = await client.recv_packet()
    except StreamProtocolParseError:
        print("Received something, but was not valid")
    except TimeoutError:
        print("Timed out")
    else:
        print(f"Received packet: {packet!r}")


async def recv_packet_example3_trio(client: AsyncTCPNetworkClient[Any, Any]) -> None:
    # [start]
    try:
        with trio.fail_after(30):
            packet = await client.recv_packet()
    except StreamProtocolParseError:
        print("Received something, but was not valid")
    except trio.TooSlowError:
        print("Timed out")
    else:
        print(f"Received packet: {packet!r}")


async def recv_packet_example3_backend_api(client: AsyncTCPNetworkClient[Any, Any]) -> None:
    # [start]
    try:
        with client.backend().timeout(30):
            packet = await client.recv_packet()
    except StreamProtocolParseError:
        print("Received something, but was not valid")
    except TimeoutError:
        print("Timed out")
    else:
        print(f"Received packet: {packet!r}")


async def recv_packet_example4(client: AsyncTCPNetworkClient[Any, Any]) -> None:
    # [start]
    all_packets = [p async for p in client.iter_received_packets()]


async def recv_packet_example5(client: AsyncTCPNetworkClient[Any, Any]) -> None:
    # [start]
    all_packets = [p async for p in client.iter_received_packets(timeout=1)]


##################
# Advanced usage #
##################


async def send_eof_example(client: AsyncTCPNetworkClient[Any, Any]) -> None:
    # [start]
    await client.send_eof()


async def socket_proxy_example(client: AsyncTCPNetworkClient[Any, Any]) -> None:
    # [start]
    client.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, False)


async def max_recv_size_example() -> None:
    address = ("remote_address", 12345)
    protocol = StreamProtocol(JSONSerializer())

    # [start]
    async with AsyncTCPNetworkClient(address, protocol, max_recv_size=1024) as client:
        # Only do socket.recv(1024) calls
        packet = await client.recv_packet()


async def ssl_default_context_example() -> None:
    address = ("remote_address", 12345)
    protocol = StreamProtocol(JSONSerializer())

    # [start]
    async with AsyncTCPNetworkClient(address, protocol, ssl=True) as client:
        await client.send_packet({"data": 42})

        packet = await client.recv_packet()
