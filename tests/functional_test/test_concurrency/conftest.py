from __future__ import annotations

from collections.abc import AsyncGenerator, Iterator
from typing import Any, Literal

from easynetwork.lowlevel.socket import IPv4SocketAddress
from easynetwork.protocol import DatagramProtocol, StreamProtocol
from easynetwork.serializers.line import StringLineSerializer
from easynetwork.servers.abc import AbstractNetworkServer
from easynetwork.servers.handlers import AsyncBaseClientInterface, AsyncDatagramRequestHandler, AsyncStreamRequestHandler
from easynetwork.servers.standalone_tcp import StandaloneTCPNetworkServer
from easynetwork.servers.standalone_udp import StandaloneUDPNetworkServer
from easynetwork.servers.standalone_unix_datagram import StandaloneUnixDatagramServer
from easynetwork.servers.standalone_unix_stream import StandaloneUnixStreamServer
from easynetwork.servers.threads_helper import NetworkServerThread

import pytest

from ...pytest_plugins.unix_sockets import UnixSocketPathFactory
from ...tools import PlatformMarkers


class EchoRequestHandler(AsyncStreamRequestHandler[str, str], AsyncDatagramRequestHandler[str, str]):
    async def handle(self, client: AsyncBaseClientInterface[str]) -> AsyncGenerator[None, str]:
        request = yield
        await client.send_packet(request)


@pytest.fixture(
    params=[
        "TCP",
        "UDP",
        pytest.param("UNIX_STREAM", marks=[PlatformMarkers.skipif_platform_win32]),
        pytest.param("UNIX_DGRAM", marks=[PlatformMarkers.skipif_platform_win32]),
    ]
)
def ipproto(request: pytest.FixtureRequest) -> Literal["TCP", "UDP", "UNIX_STREAM", "UNIX_DGRAM"]:
    return getattr(request, "param").upper()


def _build_server(
    ipproto: Literal["TCP", "UDP", "UNIX_STREAM", "UNIX_DGRAM"], unix_socket_path_factory: UnixSocketPathFactory
) -> AbstractNetworkServer:
    serializer = StringLineSerializer()
    request_handler = EchoRequestHandler()
    match ipproto:
        case "TCP":
            return StandaloneTCPNetworkServer(None, 0, StreamProtocol(serializer), request_handler)
        case "UDP":
            return StandaloneUDPNetworkServer(None, 0, DatagramProtocol(serializer), request_handler)
        case "UNIX_STREAM":
            return StandaloneUnixStreamServer(unix_socket_path_factory(), StreamProtocol(serializer), request_handler)
        case "UNIX_DGRAM":
            return StandaloneUnixDatagramServer(unix_socket_path_factory(), DatagramProtocol(serializer), request_handler)
        case _:
            pytest.fail("Invalid ipproto")


def _run_server(server: AbstractNetworkServer) -> NetworkServerThread:
    t = NetworkServerThread(server, daemon=True)
    t.start()
    assert server.is_serving()
    return t


def _retrieve_server_address(server: AbstractNetworkServer) -> Any:
    match server:
        case StandaloneTCPNetworkServer() | StandaloneUDPNetworkServer():
            address = server.get_addresses()[0]
            if isinstance(address, IPv4SocketAddress):
                return "127.0.0.1", address.port
            return "::1", address.port
        case StandaloneUnixStreamServer() | StandaloneUnixDatagramServer():
            return server.get_addresses()[0].as_raw()
        case _:
            pytest.fail("Invalid ipproto")


@pytest.fixture
def server(
    ipproto: Literal["TCP", "UDP", "UNIX_STREAM", "UNIX_DGRAM"],
    unix_socket_path_factory: UnixSocketPathFactory,
) -> Iterator[Any]:
    with _build_server(ipproto, unix_socket_path_factory) as server:
        server_thread = _run_server(server)
        try:
            yield _retrieve_server_address(server)
        finally:
            server_thread.join(timeout=1)
