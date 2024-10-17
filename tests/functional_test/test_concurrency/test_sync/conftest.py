from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Literal

from easynetwork.clients import TCPNetworkClient, UDPNetworkClient
from easynetwork.clients.abc import AbstractNetworkClient
from easynetwork.clients.unix_datagram import UnixDatagramClient
from easynetwork.clients.unix_stream import UnixStreamClient
from easynetwork.protocol import DatagramProtocol, StreamProtocol
from easynetwork.serializers.line import StringLineSerializer

import pytest


def _build_client(
    ipproto: Literal["TCP", "UDP", "UNIX_STREAM", "UNIX_DGRAM"],
    server_address: Any,
) -> AbstractNetworkClient[str, str]:
    serializer = StringLineSerializer()
    # The retry interval is already at 1 second by default but we enfore it for the tests
    match ipproto:
        case "TCP":
            return TCPNetworkClient(server_address, StreamProtocol(serializer), retry_interval=1.0)
        case "UDP":
            return UDPNetworkClient(server_address, DatagramProtocol(serializer), retry_interval=1.0)
        case "UNIX_STREAM":
            return UnixStreamClient(server_address, StreamProtocol(serializer), retry_interval=1.0)
        case "UNIX_DGRAM":
            return UnixDatagramClient(server_address, DatagramProtocol(serializer), retry_interval=1.0)
        case _:
            pytest.fail("Invalid ipproto")


@pytest.fixture
def client(
    ipproto: Literal["TCP", "UDP", "UNIX_STREAM", "UNIX_DGRAM"],
    server: Any,
) -> Iterator[AbstractNetworkClient[str, str]]:
    with _build_client(ipproto, server) as client:
        yield client
