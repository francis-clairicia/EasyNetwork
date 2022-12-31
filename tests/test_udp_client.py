# -*- coding: Utf-8 -*-

from __future__ import annotations

from socket import AF_INET, SOCK_DGRAM, socket as Socket
from typing import Any

from easynetwork.client.udp import UDPNetworkClient
from easynetwork.protocol import JSONNetworkProtocol, PickleNetworkProtocol

import pytest


def test_default(udp_server: tuple[str, int]) -> None:
    with UDPNetworkClient[Any, Any](udp_server, PickleNetworkProtocol()) as client:
        client.send_packet({"data": [5, 2]})
        assert client.recv_packet() == {"data": [5, 2]}
        client.send_packet("Hello")
        assert client.recv_packet() == "Hello"
        assert len(client.recv_packets(timeout=0)) == 0
        with pytest.raises(TimeoutError):
            client.recv_packet_no_block()
        assert client.recv_packet_no_block(default=None) is None


def test_custom_socket(udp_server: tuple[str, int]) -> None:
    with Socket(AF_INET, SOCK_DGRAM) as socket:
        socket.bind(("", 0))
        socket.connect(udp_server)
        client: UDPNetworkClient[Any, Any] = UDPNetworkClient(socket, PickleNetworkProtocol())
        client.send_packet({"data": [5, 2]})
        assert client.recv_packet() == {"data": [5, 2]}
        client.send_packet("Hello")
        assert client.recv_packet() == "Hello"


def test_custom_protocol(udp_server: tuple[str, int]) -> None:
    with UDPNetworkClient[Any, Any](udp_server, protocol=JSONNetworkProtocol()) as client:
        client.send_packet({"data": [5, 2]})
        assert client.recv_packet() == {"data": [5, 2]}
        client.send_packet("Hello")
        assert client.recv_packet() == "Hello"


def test_several_successive_send(udp_server: tuple[str, int]) -> None:
    with UDPNetworkClient[Any, Any](udp_server, protocol=PickleNetworkProtocol()) as client:
        client.send_packet({"data": [5, 2]})
        client.send_packet("Hello")
        client.send_packet(132)
        assert client.recv_packet() == {"data": [5, 2]}
        assert client.recv_packet() == "Hello"
        assert client.recv_packet() == 132
