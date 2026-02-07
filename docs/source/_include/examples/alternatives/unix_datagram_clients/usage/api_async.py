from __future__ import annotations

import asyncio
import socket
from typing import Any

import trio

from easynetwork.clients.async_unix_datagram import AsyncUnixDatagramClient
from easynetwork.exceptions import DatagramProtocolParseError

###############
# Basic usage #
###############


async def send_packet_example1(client: AsyncUnixDatagramClient[Any, Any]) -> None:
    # [start]
    await client.send_packet({"data": 42})


async def recv_packet_example1(client: AsyncUnixDatagramClient[Any, Any]) -> None:
    # [start]
    packet = await client.recv_packet()
    print(f"Received packet: {packet!r}")


async def recv_packet_example2_asyncio(client: AsyncUnixDatagramClient[Any, Any]) -> None:
    # [start]
    try:
        async with asyncio.timeout(30):
            packet = await client.recv_packet()
    except TimeoutError:
        print("Timed out")
    else:
        print(f"Received packet: {packet!r}")


async def recv_packet_example2_trio(client: AsyncUnixDatagramClient[Any, Any]) -> None:
    # [start]
    try:
        with trio.fail_after(30):
            packet = await client.recv_packet()
    except trio.TooSlowError:
        print("Timed out")
    else:
        print(f"Received packet: {packet!r}")


async def recv_packet_example2_backend_api(client: AsyncUnixDatagramClient[Any, Any]) -> None:
    # [start]
    try:
        with client.backend().timeout(30):
            packet = await client.recv_packet()
    except TimeoutError:
        print("Timed out")
    else:
        print(f"Received packet: {packet!r}")


async def recv_packet_example3_asyncio(client: AsyncUnixDatagramClient[Any, Any]) -> None:
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


async def recv_packet_example3_trio(client: AsyncUnixDatagramClient[Any, Any]) -> None:
    # [start]
    try:
        with trio.fail_after(30):
            packet = await client.recv_packet()
    except DatagramProtocolParseError:
        print("Received something, but was not valid")
    except trio.TooSlowError:
        print("Timed out")
    else:
        print(f"Received packet: {packet!r}")


async def recv_packet_example3_backend_api(client: AsyncUnixDatagramClient[Any, Any]) -> None:
    # [start]
    try:
        with client.backend().timeout(30):
            packet = await client.recv_packet()
    except DatagramProtocolParseError:
        print("Received something, but was not valid")
    except TimeoutError:
        print("Timed out")
    else:
        print(f"Received packet: {packet!r}")


async def recv_packet_example4(client: AsyncUnixDatagramClient[Any, Any]) -> None:
    # [start]
    all_packets = [p async for p in client.iter_received_packets()]


async def recv_packet_example5(client: AsyncUnixDatagramClient[Any, Any]) -> None:
    # [start]
    all_packets = [p async for p in client.iter_received_packets(timeout=1)]


##################
# Advanced usage #
##################


async def socket_proxy_example(client: AsyncUnixDatagramClient[Any, Any]) -> None:
    # [start]
    client.socket.setsockopt(socket.SOL_SOCKET, socket.SO_DEBUG, True)


async def send_packet_with_ancillary_example1(client: AsyncUnixDatagramClient[Any, Any]) -> None:
    # [start]
    from easynetwork.lowlevel.socket import SocketAncillary

    ancillary = SocketAncillary()
    ancillary.add_fds([4])
    await client.send_packet({"data": 42}, ancillary_data=ancillary)


async def recv_packet_with_ancillary_example1(client: AsyncUnixDatagramClient[Any, Any]) -> None:
    # [start]
    from easynetwork.lowlevel.socket import SCMCredentials, SCMRights, SocketAncillary

    ancillary = SocketAncillary()
    packet = await client.recv_packet(ancillary_data=ancillary)
    print(f"Received packet: {packet!r}")
    for message in ancillary.messages():
        match message:
            case SCMRights(fds):
                for fd in fds:
                    print(f"Received file descriptor: {fd}")
            case SCMCredentials(credentials):
                for ucred in credentials:
                    print(f"Received unix credential: {ucred}")


async def recv_packet_with_ancillary_example2(client: AsyncUnixDatagramClient[Any, Any]) -> None:
    # [start]
    from socket import CMSG_LEN

    from easynetwork.lowlevel.socket import SocketAncillary

    max_fds = 128
    ancillary = SocketAncillary()
    packet = await client.recv_packet(ancillary_data=ancillary, ancillary_bufsize=CMSG_LEN(max_fds * 4))
    print(f"Received packet: {packet!r}")
    for fd in ancillary.iter_fds():
        print(f"Received file descriptor: {fd}")
