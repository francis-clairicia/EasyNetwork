from __future__ import annotations

import socket
from typing import Any

from easynetwork.clients.unix_stream import UnixStreamClient
from easynetwork.exceptions import StreamProtocolParseError
from easynetwork.protocol import StreamProtocol
from easynetwork.serializers import JSONSerializer

###############
# Basic usage #
###############


def send_packet_example1(client: UnixStreamClient[Any, Any]) -> None:
    # [start]
    client.send_packet({"data": 42})


def recv_packet_example1(client: UnixStreamClient[Any, Any]) -> None:
    # [start]
    packet = client.recv_packet()
    print(f"Received packet: {packet!r}")


def recv_packet_example2(client: UnixStreamClient[Any, Any]) -> None:
    # [start]
    try:
        packet = client.recv_packet(timeout=30)
    except TimeoutError:
        print("Timed out")
    else:
        print(f"Received packet: {packet!r}")


def recv_packet_example3(client: UnixStreamClient[Any, Any]) -> None:
    # [start]
    try:
        packet = client.recv_packet(timeout=30)
    except StreamProtocolParseError:
        print("Received something, but was not valid")
    except TimeoutError:
        print("Timed out")
    else:
        print(f"Received packet: {packet!r}")


def recv_packet_example4(client: UnixStreamClient[Any, Any]) -> None:
    # [start]
    all_packets = [p for p in client.iter_received_packets()]


def recv_packet_example5(client: UnixStreamClient[Any, Any]) -> None:
    # [start]
    all_packets = [p for p in client.iter_received_packets(timeout=1)]


##################
# Advanced usage #
##################


def send_eof_example(client: UnixStreamClient[Any, Any]) -> None:
    # [start]
    client.send_eof()


def socket_peer_credentials_example(client: UnixStreamClient[Any, Any]) -> None:
    # [start]
    peer_creds = client.get_peer_credentials()
    print(f"pid={peer_creds.pid}, user_id={peer_creds.uid}, group_id={peer_creds.gid}")


def socket_proxy_example(client: UnixStreamClient[Any, Any]) -> None:
    # [start]
    client.socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, False)


def max_recv_size_example() -> None:
    address = "peer_sock"
    protocol = StreamProtocol(JSONSerializer())

    # [start]
    with UnixStreamClient(address, protocol, max_recv_size=1024) as client:
        # Only do socket.recv(1024) calls
        packet = client.recv_packet()
