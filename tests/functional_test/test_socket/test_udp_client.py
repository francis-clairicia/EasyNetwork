# -*- coding: Utf-8 -*-

from __future__ import annotations

from socket import AF_INET, SOCK_DGRAM, socket as Socket
from typing import Any

from easynetwork.client.udp import UDPNetworkClient
from easynetwork.protocol import DatagramProtocol
from easynetwork.serializers import JSONSerializer, PickleSerializer

import pytest


def test_default(udp_server: tuple[str, int]) -> None:
    with UDPNetworkClient[Any, Any](udp_server, DatagramProtocol(PickleSerializer())) as client:
        client.send_packet({"data": [5, 2]})
        assert client.recv_packet() == {"data": [5, 2]}
        client.send_packet("Hello")
        assert client.recv_packet() == "Hello"
        assert len(list(client.iter_received_packets(timeout=0))) == 0
        with pytest.raises(TimeoutError):
            client.recv_packet_no_block()
        assert client.recv_packet_no_block(default=None) is None


def test_custom_socket(udp_server: tuple[str, int]) -> None:
    with Socket(AF_INET, SOCK_DGRAM) as socket:
        socket.bind(("", 0))
        socket.connect(udp_server)
        client: UDPNetworkClient[Any, Any] = UDPNetworkClient(socket, DatagramProtocol(PickleSerializer()))
        client.send_packet({"data": [5, 2]})
        assert client.recv_packet() == {"data": [5, 2]}
        client.send_packet("Hello")
        assert client.recv_packet() == "Hello"


def test_custom_serializer(udp_server: tuple[str, int]) -> None:
    with UDPNetworkClient[Any, Any](udp_server, protocol=DatagramProtocol(JSONSerializer())) as client:
        client.send_packet({"data": [5, 2]})
        assert client.recv_packet() == {"data": [5, 2]}
        client.send_packet(["Hello"])
        assert client.recv_packet() == ["Hello"]


def test_several_successive_send(udp_server: tuple[str, int]) -> None:
    with UDPNetworkClient[Any, Any](udp_server, protocol=DatagramProtocol(PickleSerializer())) as client:
        client.send_packet({"data": [5, 2]})
        client.send_packet([132])
        assert client.recv_packet() == {"data": [5, 2]}
        assert client.recv_packet() == [132]
