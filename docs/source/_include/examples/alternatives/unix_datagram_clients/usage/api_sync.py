from __future__ import annotations

import socket
from typing import Any

from easynetwork.clients.unix_datagram import UnixDatagramClient
from easynetwork.exceptions import DatagramProtocolParseError

###############
# Basic usage #
###############


def send_packet_example1(client: UnixDatagramClient[Any, Any]) -> None:
    # [start]
    client.send_packet({"data": 42})


def recv_packet_example1(client: UnixDatagramClient[Any, Any]) -> None:
    # [start]
    packet = client.recv_packet()
    print(f"Received packet: {packet!r}")


def recv_packet_example2(client: UnixDatagramClient[Any, Any]) -> None:
    # [start]
    try:
        packet = client.recv_packet(timeout=30)
    except TimeoutError:
        print("Timed out")
    else:
        print(f"Received packet: {packet!r}")


def recv_packet_example3(client: UnixDatagramClient[Any, Any]) -> None:
    # [start]
    try:
        packet = client.recv_packet(timeout=30)
    except DatagramProtocolParseError:
        print("Received something, but was not valid")
    except TimeoutError:
        print("Timed out")
    else:
        print(f"Received packet: {packet!r}")


def recv_packet_example4(client: UnixDatagramClient[Any, Any]) -> None:
    # [start]
    all_packets = [p for p in client.iter_received_packets()]


def recv_packet_example5(client: UnixDatagramClient[Any, Any]) -> None:
    # [start]
    all_packets = [p for p in client.iter_received_packets(timeout=1)]


##################
# Advanced usage #
##################


def socket_proxy_example(client: UnixDatagramClient[Any, Any]) -> None:
    # [start]
    client.socket.setsockopt(socket.SOL_SOCKET, socket.SO_DEBUG, True)


def send_packet_with_ancillary_example1(client: UnixDatagramClient[Any, Any]) -> None:
    # [start]
    from easynetwork.lowlevel.socket import SocketAncillary

    ancillary = SocketAncillary()
    ancillary.add_fds([4])
    client.send_packet({"data": 42}, ancillary_data=ancillary)


def recv_packet_with_ancillary_example1(client: UnixDatagramClient[Any, Any]) -> None:
    # [start]
    from easynetwork.lowlevel.socket import SCMCredentials, SCMRights, SocketAncillary

    ancillary = SocketAncillary()
    packet = client.recv_packet(ancillary_data=ancillary)
    print(f"Received packet: {packet!r}")
    for message in ancillary.messages():
        match message:
            case SCMRights(fds):
                for fd in fds:
                    print(f"Received file descriptor: {fd}")
            case SCMCredentials(credentials):
                for ucred in credentials:
                    print(f"Received unix credential: {ucred}")


def recv_packet_with_ancillary_example2(client: UnixDatagramClient[Any, Any]) -> None:
    # [start]
    from socket import CMSG_LEN

    from easynetwork.lowlevel.socket import SocketAncillary

    max_fds = 128
    ancillary = SocketAncillary()
    packet = client.recv_packet(ancillary_data=ancillary, ancillary_bufsize=CMSG_LEN(max_fds * 4))
    print(f"Received packet: {packet!r}")
    for fd in ancillary.iter_fds():
        print(f"Received file descriptor: {fd}")
