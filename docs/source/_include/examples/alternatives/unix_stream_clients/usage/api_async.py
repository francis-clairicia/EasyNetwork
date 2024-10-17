from __future__ import annotations

import asyncio
import socket
from typing import Any

import trio

from easynetwork.clients.async_unix_stream import AsyncUnixStreamClient
from easynetwork.exceptions import StreamProtocolParseError
from easynetwork.protocol import StreamProtocol
from easynetwork.serializers import JSONSerializer

###############
# Basic usage #
###############


async def send_packet_example1(client: AsyncUnixStreamClient[Any, Any]) -> None:
    # [start]
    await client.send_packet({"data": 42})


async def recv_packet_example1(client: AsyncUnixStreamClient[Any, Any]) -> None:
    # [start]
    packet = await client.recv_packet()
    print(f"Received packet: {packet!r}")


async def recv_packet_example2_asyncio(client: AsyncUnixStreamClient[Any, Any]) -> None:
    # [start]
    try:
        async with asyncio.timeout(30):
            packet = await client.recv_packet()
    except TimeoutError:
        print("Timed out")
    else:
        print(f"Received packet: {packet!r}")


async def recv_packet_example2_trio(client: AsyncUnixStreamClient[Any, Any]) -> None:
    # [start]
    try:
        with trio.fail_after(30):
            packet = await client.recv_packet()
    except trio.TooSlowError:
        print("Timed out")
    else:
        print(f"Received packet: {packet!r}")


async def recv_packet_example2_backend_api(client: AsyncUnixStreamClient[Any, Any]) -> None:
    # [start]
    try:
        with client.backend().timeout(30):
            packet = await client.recv_packet()
    except TimeoutError:
        print("Timed out")
    else:
        print(f"Received packet: {packet!r}")


async def recv_packet_example3_asyncio(client: AsyncUnixStreamClient[Any, Any]) -> None:
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


async def recv_packet_example3_trio(client: AsyncUnixStreamClient[Any, Any]) -> None:
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


async def recv_packet_example3_backend_api(client: AsyncUnixStreamClient[Any, Any]) -> None:
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


async def recv_packet_example4(client: AsyncUnixStreamClient[Any, Any]) -> None:
    # [start]
    all_packets = [p async for p in client.iter_received_packets()]


async def recv_packet_example5(client: AsyncUnixStreamClient[Any, Any]) -> None:
    # [start]
    all_packets = [p async for p in client.iter_received_packets(timeout=1)]


##################
# Advanced usage #
##################


async def send_eof_example(client: AsyncUnixStreamClient[Any, Any]) -> None:
    # [start]
    await client.send_eof()


async def socket_peer_credentials_example(client: AsyncUnixStreamClient[Any, Any]) -> None:
    # [start]
    peer_creds = client.get_peer_credentials()
    print(f"pid={peer_creds.pid}, user_id={peer_creds.uid}, group_id={peer_creds.gid}")


async def socket_proxy_example(client: AsyncUnixStreamClient[Any, Any]) -> None:
    # [start]
    client.socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, False)


async def max_recv_size_example() -> None:
    address = "peer_sock"
    protocol = StreamProtocol(JSONSerializer())

    # [start]
    async with AsyncUnixStreamClient(address, protocol, max_recv_size=1024) as client:
        # Only do socket.recv(1024) calls
        packet = await client.recv_packet()
