from __future__ import annotations

import contextlib
import threading
from collections.abc import AsyncGenerator, Iterator
from typing import Literal

from easynetwork.api_async.server.abc import AbstractAsyncNetworkServer
from easynetwork.api_async.server.handler import AsyncBaseClientInterface, AsyncDatagramRequestHandler, AsyncStreamRequestHandler
from easynetwork.api_sync.server.abc import AbstractNetworkServer
from easynetwork.api_sync.server.tcp import StandaloneTCPNetworkServer
from easynetwork.api_sync.server.udp import StandaloneUDPNetworkServer
from easynetwork.protocol import DatagramProtocol, StreamProtocol
from easynetwork.serializers.line import StringLineSerializer

import pytest


class EchoRequestHandler(AsyncStreamRequestHandler[str, str], AsyncDatagramRequestHandler[str, str]):
    async def service_init(self, exit_stack: contextlib.AsyncExitStack, server: AbstractAsyncNetworkServer) -> None:
        pass

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
            return StandaloneUDPNetworkServer("localhost", 0, DatagramProtocol(serializer), request_handler)
        case _:
            pytest.fail("Invalid ipproto")


def _run_server(server: AbstractNetworkServer) -> None:
    is_up_event = threading.Event()
    t = threading.Thread(target=server.serve_forever, kwargs={"is_up_event": is_up_event}, daemon=True)
    t.start()

    if not is_up_event.wait(timeout=1):
        raise TimeoutError("Too long to start")
    assert server.is_serving()


def _retrieve_server_port(server: AbstractNetworkServer) -> int:
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
