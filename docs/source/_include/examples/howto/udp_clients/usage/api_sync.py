from __future__ import annotations

import socket
from typing import Any

from easynetwork.clients import UDPNetworkClient
from easynetwork.exceptions import DatagramProtocolParseError

###############
# Basic usage #
###############


def send_packet_example1(client: UDPNetworkClient[Any, Any]) -> None:
    # [start]
    client.send_packet({"data": 42})


def recv_packet_example1(client: UDPNetworkClient[Any, Any]) -> None:
    # [start]
    packet = client.recv_packet()
    print(f"Received packet: {packet!r}")


def recv_packet_example2(client: UDPNetworkClient[Any, Any]) -> None:
    # [start]
    try:
        packet = client.recv_packet(timeout=30)
    except TimeoutError:
        print("Timed out")
    else:
        print(f"Received packet: {packet!r}")


def recv_packet_example3(client: UDPNetworkClient[Any, Any]) -> None:
    # [start]
    try:
        packet = client.recv_packet(timeout=30)
    except DatagramProtocolParseError:
        print("Received something, but was not valid")
    except TimeoutError:
        print("Timed out")
    else:
        print(f"Received packet: {packet!r}")


def recv_packet_example4(client: UDPNetworkClient[Any, Any]) -> None:
    # [start]
    all_packets = [p for p in client.iter_received_packets()]


def recv_packet_example5(client: UDPNetworkClient[Any, Any]) -> None:
    # [start]
    all_packets = [p for p in client.iter_received_packets(timeout=1)]


##################
# Advanced usage #
##################


def socket_proxy_example(client: UDPNetworkClient[Any, Any]) -> None:
    # [start]
    client.socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, True)
