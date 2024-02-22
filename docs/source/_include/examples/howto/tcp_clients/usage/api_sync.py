from __future__ import annotations

import socket
from typing import Any

from easynetwork.clients import TCPNetworkClient
from easynetwork.exceptions import StreamProtocolParseError
from easynetwork.protocol import StreamProtocol
from easynetwork.serializers import JSONSerializer

###############
# Basic usage #
###############


def send_packet_example1(client: TCPNetworkClient[Any, Any]) -> None:
    # [start]
    client.send_packet({"data": 42})


def recv_packet_example1(client: TCPNetworkClient[Any, Any]) -> None:
    # [start]
    packet = client.recv_packet()
    print(f"Received packet: {packet!r}")


def recv_packet_example2(client: TCPNetworkClient[Any, Any]) -> None:
    # [start]
    try:
        packet = client.recv_packet(timeout=30)
    except TimeoutError:
        print("Timed out")
    else:
        print(f"Received packet: {packet!r}")


def recv_packet_example3(client: TCPNetworkClient[Any, Any]) -> None:
    # [start]
    try:
        packet = client.recv_packet(timeout=30)
    except StreamProtocolParseError:
        print("Received something, but was not valid")
    except TimeoutError:
        print("Timed out")
    else:
        print(f"Received packet: {packet!r}")


def recv_packet_example4(client: TCPNetworkClient[Any, Any]) -> None:
    # [start]
    all_packets = [p for p in client.iter_received_packets()]


def recv_packet_example5(client: TCPNetworkClient[Any, Any]) -> None:
    # [start]
    all_packets = [p for p in client.iter_received_packets(timeout=1)]


##################
# Advanced usage #
##################


def send_eof_example(client: TCPNetworkClient[Any, Any]) -> None:
    # [start]
    client.send_eof()


def socket_proxy_example(client: TCPNetworkClient[Any, Any]) -> None:
    # [start]
    client.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, False)


def max_recv_size_example() -> None:
    address = ("remote_address", 12345)
    protocol = StreamProtocol(JSONSerializer())

    # [start]
    with TCPNetworkClient(address, protocol, max_recv_size=1024) as client:
        # Only do socket.recv(1024) calls
        packet = client.recv_packet()


def ssl_default_context_example() -> None:
    address = ("remote_address", 12345)
    protocol = StreamProtocol(JSONSerializer())

    # [start]
    with TCPNetworkClient(address, protocol, ssl=True) as client:
        client.send_packet({"data": 42})

        packet = client.recv_packet()
