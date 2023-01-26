# -*- coding: Utf-8 -*-

from __future__ import annotations

import time
from functools import partial
from socket import AF_INET, SOCK_STREAM, socket as Socket
from typing import Any, Generator

from easynetwork.client.tcp import TCPNetworkClient
from easynetwork.protocol import StreamProtocol
from easynetwork.serializers import AbstractIncrementalPacketSerializer, JSONSerializer, PickleSerializer

import pytest


def test_default(tcp_server: tuple[str, int]) -> None:
    with TCPNetworkClient[Any, Any](tcp_server, StreamProtocol(PickleSerializer())) as client:
        client.send_packet({"data": [5, 2]})
        assert client.recv_packet() == {"data": [5, 2]}
        client.send_packet("Hello")
        assert client.recv_packet() == "Hello"
        assert len(list(client.iter_received_packets(timeout=0))) == 0
        with pytest.raises(TimeoutError):
            client.recv_packet_no_block()
        assert client.recv_packet_no_block(default=None) is None


def test_custom_socket(tcp_server: tuple[str, int]) -> None:
    with Socket(AF_INET, SOCK_STREAM) as s:
        s.connect(tcp_server)
        client: TCPNetworkClient[Any, Any] = TCPNetworkClient(s, StreamProtocol(PickleSerializer()))
        client.send_packet({"data": [5, 2]})
        assert client.recv_packet() == {"data": [5, 2]}
        client.send_packet("Hello")
        assert client.recv_packet() == "Hello"


class StringSerializer(AbstractIncrementalPacketSerializer[str, str]):
    def incremental_serialize(self, packet: str) -> Generator[bytes, None, None]:
        if not isinstance(packet, str):
            raise ValueError("Invalid string")
        yield from map(partial(str.encode, encoding="ascii"), packet.splitlines(True))

    def incremental_deserialize(self) -> Generator[None, bytes, tuple[str, bytes]]:
        data: str = str()
        while True:
            data += (yield).decode("ascii")
            if "\n" in data:
                packet, _, data = data.partition("\n")
                return packet, data.encode("ascii")


def test_multiple_requests(tcp_server: tuple[str, int]) -> None:
    with TCPNetworkClient(tcp_server, protocol=StreamProtocol(StringSerializer())) as client:
        client.send_packet("A\nB\nC\nD\n")
        time.sleep(0.1)
        assert list(client.iter_received_packets()) == ["A", "B", "C", "D"]
        client.send_packet("E\nF\nG\nH\nI")
        time.sleep(0.1)
        assert client.recv_packet() == "E"
        assert client.recv_packet() == "F"
        assert list(client.iter_received_packets()) == ["G", "H"]
        client.send_packet("J\n")
        assert client.recv_packet() == "IJ"

        with pytest.raises(ValueError, match=r"^Invalid string$"):
            client.send_packet(5)  # type: ignore[arg-type]


def test_several_successive_send_using_pickling_serializer(tcp_server: tuple[str, int]) -> None:
    with TCPNetworkClient[Any, Any](tcp_server, protocol=StreamProtocol(PickleSerializer())) as client:
        client.send_packet({"data": [5, 2]})
        client.send_packet("Hello")
        client.send_packet(132)
        assert client.recv_packet() == {"data": [5, 2]}
        assert client.recv_packet() == "Hello"
        assert client.recv_packet() == 132


def test_several_successive_send_using_json_serializer(tcp_server: tuple[str, int]) -> None:
    with TCPNetworkClient[Any, Any](tcp_server, protocol=StreamProtocol(JSONSerializer())) as client:
        client.send_packet({"data": [5, 2]})
        client.send_packet([132])
        assert client.recv_packet() == {"data": [5, 2]}
        assert client.recv_packet() == [132]
