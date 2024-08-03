from __future__ import annotations

from collections.abc import AsyncGenerator, Iterator

from easynetwork.clients.async_tcp import AsyncTCPNetworkClient
from easynetwork.clients.async_udp import AsyncUDPNetworkClient
from easynetwork.clients.tcp import TCPNetworkClient
from easynetwork.clients.udp import UDPNetworkClient
from easynetwork.lowlevel.api_async.backend.utils import BuiltinAsyncBackendLiteral
from easynetwork.protocol import AnyStreamProtocolType, DatagramProtocol
from easynetwork.servers.abc import AbstractNetworkServer
from easynetwork.servers.handlers import AsyncBaseClientInterface, AsyncDatagramRequestHandler, AsyncStreamRequestHandler
from easynetwork.servers.standalone_tcp import StandaloneTCPNetworkServer
from easynetwork.servers.standalone_udp import StandaloneUDPNetworkServer
from easynetwork.servers.threads_helper import NetworkServerThread

import pytest


class EchoRequestHandler(AsyncStreamRequestHandler[str, str], AsyncDatagramRequestHandler[str, str]):
    async def handle(self, client: AsyncBaseClientInterface[str]) -> AsyncGenerator[None, str]:
        request = yield
        await client.send_packet(request)


@pytest.mark.flaky(retries=3, delay=1)
class BaseTestNetworkServer:
    @pytest.fixture(
        params=[
            pytest.param("asyncio"),
            pytest.param("trio", marks=pytest.mark.feature_trio(async_test_auto_mark=False)),
        ],
        ids=lambda p: f"server_backend=={p!r}",
    )
    @staticmethod
    def server_backend(request: pytest.FixtureRequest) -> BuiltinAsyncBackendLiteral:
        return request.param

    @pytest.fixture(
        params=[
            pytest.param("asyncio", marks=pytest.mark.asyncio),
            pytest.param("trio", marks=pytest.mark.feature_trio(async_test_auto_mark=True)),
        ],
        ids=lambda p: f"async_client_backend=={p!r}",
    )
    @staticmethod
    def async_client_backend(request: pytest.FixtureRequest) -> BuiltinAsyncBackendLiteral:
        return request.param

    @pytest.fixture(autouse=True)
    @staticmethod
    def start_server(
        server: AbstractNetworkServer,
    ) -> Iterator[NetworkServerThread]:
        with server:
            server_thread = NetworkServerThread(server, daemon=True)
            server_thread.start()

            yield server_thread

            server_thread.join(timeout=1)


class TestNetworkTCP(BaseTestNetworkServer):
    @pytest.fixture
    @staticmethod
    def server(
        server_backend: BuiltinAsyncBackendLiteral,
        stream_protocol: AnyStreamProtocolType[str, str],
    ) -> StandaloneTCPNetworkServer[str, str]:
        return StandaloneTCPNetworkServer("127.0.0.1", 0, stream_protocol, EchoRequestHandler(), backend=server_backend)

    @pytest.fixture
    @staticmethod
    def server_address(server: StandaloneTCPNetworkServer[str, str]) -> tuple[str, int]:
        port = server.get_addresses()[0].port
        return ("localhost", port)

    def test____blocking_client____echo(
        self,
        server_address: tuple[str, int],
        stream_protocol: AnyStreamProtocolType[str, str],
    ) -> None:

        with TCPNetworkClient(server_address, stream_protocol, connect_timeout=1) as client:

            # Sequential read/write
            for i in range(3):
                client.send_packet(f"Hello world {i}")
                assert client.recv_packet(timeout=1) == f"Hello world {i}"

            # Several write
            for i in range(3):
                client.send_packet(f"Hello world {i}")
            for i in range(3):
                assert client.recv_packet(timeout=1) == f"Hello world {i}"

    async def test____asynchronous_client____echo(
        self,
        async_client_backend: BuiltinAsyncBackendLiteral,
        server_address: tuple[str, int],
        stream_protocol: AnyStreamProtocolType[str, str],
    ) -> None:

        async with AsyncTCPNetworkClient(server_address, stream_protocol, backend=async_client_backend) as client:

            # Sequential read/write
            for i in range(3):
                await client.send_packet(f"Hello world {i}")
                with client.backend().timeout(1):
                    assert (await client.recv_packet()) == f"Hello world {i}"

            # Several write
            for i in range(3):
                await client.send_packet(f"Hello world {i}")
            for i in range(3):
                with client.backend().timeout(1):
                    assert (await client.recv_packet()) == f"Hello world {i}"


class TestNetworkUDP(BaseTestNetworkServer):
    @pytest.fixture
    @staticmethod
    def server(
        server_backend: BuiltinAsyncBackendLiteral,
        datagram_protocol: DatagramProtocol[str, str],
    ) -> StandaloneUDPNetworkServer[str, str]:
        return StandaloneUDPNetworkServer("127.0.0.1", 0, datagram_protocol, EchoRequestHandler(), backend=server_backend)

    @pytest.fixture
    @staticmethod
    def server_address(server: StandaloneUDPNetworkServer[str, str]) -> tuple[str, int]:
        port = server.get_addresses()[0].port
        return ("127.0.0.1", port)

    def test____blocking_client____echo(
        self,
        server_address: tuple[str, int],
        datagram_protocol: DatagramProtocol[str, str],
    ) -> None:

        with UDPNetworkClient(server_address, datagram_protocol) as client:

            # Sequential read/write
            for i in range(3):
                client.send_packet(f"Hello world {i}")
                assert client.recv_packet(timeout=1) == f"Hello world {i}"

            # Several write
            for i in range(3):
                client.send_packet(f"Hello world {i}")
            for i in range(3):
                assert client.recv_packet(timeout=1) == f"Hello world {i}"

    async def test____asynchronous_client____echo(
        self,
        async_client_backend: BuiltinAsyncBackendLiteral,
        server_address: tuple[str, int],
        datagram_protocol: DatagramProtocol[str, str],
    ) -> None:

        async with AsyncUDPNetworkClient(server_address, datagram_protocol, backend=async_client_backend) as client:

            # Sequential read/write
            for i in range(3):
                await client.send_packet(f"Hello world {i}")
                with client.backend().timeout(1):
                    assert (await client.recv_packet()) == f"Hello world {i}"

            # Several write
            for i in range(3):
                await client.send_packet(f"Hello world {i}")
            for i in range(3):
                with client.backend().timeout(1):
                    assert (await client.recv_packet()) == f"Hello world {i}"
