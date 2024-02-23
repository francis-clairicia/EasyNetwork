from __future__ import annotations

import threading
from collections.abc import AsyncGenerator, Iterator
from typing import Literal

from easynetwork.lowlevel.socket import IPv4SocketAddress
from easynetwork.protocol import DatagramProtocol, StreamProtocol
from easynetwork.serializers.line import StringLineSerializer
from easynetwork.servers.abc import AbstractNetworkServer
from easynetwork.servers.handlers import AsyncBaseClientInterface, AsyncDatagramRequestHandler, AsyncStreamRequestHandler
from easynetwork.servers.standalone_tcp import StandaloneTCPNetworkServer
from easynetwork.servers.standalone_udp import StandaloneUDPNetworkServer

import pytest


class EchoRequestHandler(AsyncStreamRequestHandler[str, str], AsyncDatagramRequestHandler[str, str]):
    async def handle(self, client: AsyncBaseClientInterface[str]) -> AsyncGenerator[None, str]:
        request = yield
        await client.send_packet(request)


@pytest.fixture(params=["TCP", "UDP"])
def ipproto(request: pytest.FixtureRequest) -> Literal["TCP", "UDP"]:
    return getattr(request, "param").upper()


def _build_server(ipproto: Literal["TCP", "UDP"]) -> AbstractNetworkServer:
    serializer = StringLineSerializer()
    request_handler = EchoRequestHandler()
    match ipproto:
        case "TCP":
            return StandaloneTCPNetworkServer(None, 0, StreamProtocol(serializer), request_handler)
        case "UDP":
            return StandaloneUDPNetworkServer(None, 0, DatagramProtocol(serializer), request_handler)
        case _:
            pytest.fail("Invalid ipproto")


def _run_server(server: AbstractNetworkServer) -> None:
    is_up_event = threading.Event()
    t = threading.Thread(target=server.serve_forever, kwargs={"is_up_event": is_up_event}, daemon=True)
    t.start()

    if not is_up_event.wait(timeout=1):
        raise TimeoutError("Too long to start")
    assert server.is_serving()


def _retrieve_server_address(server: AbstractNetworkServer) -> tuple[str, int]:
    address = server.get_addresses()[0]
    if isinstance(address, IPv4SocketAddress):
        return "127.0.0.1", address.port
    return "::1", address.port


@pytest.fixture
def server(ipproto: Literal["TCP", "UDP"]) -> Iterator[tuple[str, int]]:
    with _build_server(ipproto) as server:
        try:
            _run_server(server)
            yield _retrieve_server_address(server)
        finally:
            server.shutdown()
