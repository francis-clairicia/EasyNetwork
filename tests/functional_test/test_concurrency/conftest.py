# -*- coding: utf-8 -*-

from __future__ import annotations

import threading
from typing import AsyncGenerator, Iterator, Literal

from easynetwork.api_async.server.handler import AsyncBaseRequestHandler, AsyncClientInterface
from easynetwork.api_async.server.standalone import (
    AbstractStandaloneNetworkServer,
    StandaloneTCPNetworkServer,
    StandaloneUDPNetworkServer,
)
from easynetwork.exceptions import BaseProtocolParseError
from easynetwork.protocol import DatagramProtocol, StreamProtocol
from easynetwork.serializers.line import StringLineSerializer

import pytest


class EchoRequestHandler(AsyncBaseRequestHandler[str, str]):
    async def handle(self, client: AsyncClientInterface[str]) -> AsyncGenerator[None, str]:
        request = yield
        await client.send_packet(request)

    async def bad_request(self, client: AsyncClientInterface[str], exc: BaseProtocolParseError, /) -> None:
        await client.aclose()


@pytest.fixture(params=["TCP", "UDP"])
def ipproto(request: pytest.FixtureRequest) -> Literal["TCP", "UDP"]:
    return getattr(request, "param").upper()


def _build_server(ipproto: Literal["TCP", "UDP"]) -> AbstractStandaloneNetworkServer:
    serializer = StringLineSerializer()
    request_handler = EchoRequestHandler()
    match ipproto:
        case "TCP":
            return StandaloneTCPNetworkServer(None, 0, StreamProtocol(serializer), request_handler)
        case "UDP":
            return StandaloneUDPNetworkServer(None, 0, DatagramProtocol(serializer), request_handler)
        case _:
            pytest.fail("Invalid ipproto")


def _run_server(server: AbstractStandaloneNetworkServer) -> None:
    is_up_event = threading.Event()
    t = threading.Thread(target=server.serve_forever, kwargs={"is_up_event": is_up_event}, daemon=True)
    t.start()

    if not is_up_event.wait(timeout=1):
        raise TimeoutError("Too long to start")
    assert server.is_serving()


def _retrieve_server_port(server: AbstractStandaloneNetworkServer) -> int:
    match server:
        case StandaloneTCPNetworkServer():
            addresses = server.get_addresses()
            assert addresses
            return addresses[0].port
        case StandaloneUDPNetworkServer():
            address = server.get_address()
            assert address
            return address.port
        case _:
            pytest.fail("Cannot retrieve server port")


@pytest.fixture
def server(ipproto: Literal["TCP", "UDP"]) -> Iterator[tuple[str, int]]:
    with _build_server(ipproto) as server:
        try:
            _run_server(server)
            yield "localhost", _retrieve_server_port(server)
        finally:
            server.shutdown()
