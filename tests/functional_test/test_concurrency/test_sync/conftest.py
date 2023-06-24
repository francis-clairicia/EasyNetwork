# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import Iterator, Literal

from easynetwork.api_sync.client import AbstractNetworkClient, TCPNetworkClient, UDPNetworkClient
from easynetwork.protocol import DatagramProtocol, StreamProtocol
from easynetwork.serializers.line import StringLineSerializer

import pytest


def _build_client(ipproto: Literal["TCP", "UDP"], server_address: tuple[str, int]) -> AbstractNetworkClient[str, str]:
    serializer = StringLineSerializer()
    match ipproto:
        case "TCP":
            return TCPNetworkClient(server_address, StreamProtocol(serializer))
        case "UDP":
            return UDPNetworkClient(server_address, DatagramProtocol(serializer))
        case _:
            pytest.fail("Invalid ipproto")


@pytest.fixture
def client(ipproto: Literal["TCP", "UDP"], server: tuple[str, int]) -> Iterator[AbstractNetworkClient[str, str]]:
    with _build_client(ipproto, server) as client:
        yield client
