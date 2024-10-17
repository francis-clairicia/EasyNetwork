from __future__ import annotations

import threading
import time
from collections.abc import AsyncGenerator, Iterator

from easynetwork.exceptions import ServerAlreadyRunning, ServerClosedError
from easynetwork.protocol import AnyStreamProtocolType, DatagramProtocol
from easynetwork.servers.abc import AbstractNetworkServer
from easynetwork.servers.handlers import AsyncBaseClientInterface, AsyncDatagramRequestHandler, AsyncStreamRequestHandler
from easynetwork.servers.standalone_tcp import StandaloneTCPNetworkServer
from easynetwork.servers.standalone_udp import StandaloneUDPNetworkServer
from easynetwork.servers.standalone_unix_datagram import StandaloneUnixDatagramServer
from easynetwork.servers.standalone_unix_stream import StandaloneUnixStreamServer
from easynetwork.servers.threads_helper import NetworkServerThread

import pytest

from .....pytest_plugins.unix_sockets import UnixSocketPathFactory
from .....tools import PlatformMarkers


class EchoRequestHandler(AsyncStreamRequestHandler[str, str], AsyncDatagramRequestHandler[str, str]):
    async def handle(self, client: AsyncBaseClientInterface[str]) -> AsyncGenerator[None, str]:
        request = yield
        await client.send_packet(request)


@pytest.mark.flaky(retries=3, delay=0.1)
class BaseTestStandaloneNetworkServer:
    @pytest.fixture
    @staticmethod
    def start_server(
        server: AbstractNetworkServer,
    ) -> Iterator[NetworkServerThread]:
        with server:
            server_thread = NetworkServerThread(server, daemon=True)
            server_thread.start()

            yield server_thread

            server_thread.join(timeout=1)

    def test____is_serving____default_to_False(self, server: AbstractNetworkServer) -> None:
        with server:
            assert not server.is_serving()

    def test____shutdown____default_to_noop(self, server: AbstractNetworkServer) -> None:
        with server:
            server.shutdown()

    @pytest.mark.usefixtures("start_server")
    def test____server_close____while_server_is_running(self, server: AbstractNetworkServer) -> None:
        server.server_close()
        time.sleep(0.5)

        # There is no client so the server loop should stop by itself
        assert not server.is_serving()

    @pytest.mark.usefixtures("start_server")
    def test____shutdown____while_server_is_running(self, server: AbstractNetworkServer) -> None:
        assert server.is_serving()

        server.shutdown()
        assert not server.is_serving()

    def test____server_close____idempotent(self, server: AbstractNetworkServer) -> None:
        server.server_close()
        server.server_close()
        server.server_close()

    @pytest.mark.usefixtures("start_server")
    def test____serve_forever____error_server_already_running(self, server: AbstractNetworkServer) -> None:
        with pytest.raises(ServerAlreadyRunning):
            server.serve_forever()

    def test____serve_forever____error_server_closed(self, server: AbstractNetworkServer) -> None:
        server.server_close()

        with pytest.raises(ServerClosedError):
            server.serve_forever()

    def test____serve_forever____without_is_up_event(self, server: AbstractNetworkServer) -> None:
        with server:
            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()

            time.sleep(1)
            if not server.is_serving():
                pytest.fail("Timeout error")

            server.shutdown()
            assert not server.is_serving()
            t.join()

    def test____serve_forever____serve_several_times(self, server: AbstractNetworkServer) -> None:
        with server:
            for _ in range(3):
                assert not server.is_serving()

                server_thread = NetworkServerThread(server, daemon=True)
                server_thread.start()
                try:
                    assert server.is_serving()
                    time.sleep(0.5)
                finally:
                    server_thread.join()

    def test____server_thread____several_join(
        self,
        start_server: NetworkServerThread,
    ) -> None:
        start_server.join()
        start_server.join()


class TestStandaloneTCPNetworkServer(BaseTestStandaloneNetworkServer):
    @pytest.fixture
    @staticmethod
    def server(stream_protocol: AnyStreamProtocolType[str, str]) -> StandaloneTCPNetworkServer[str, str]:
        return StandaloneTCPNetworkServer(None, 0, stream_protocol, EchoRequestHandler(), "asyncio")

    def test____socket_property____server_is_not_running(self, server: StandaloneTCPNetworkServer[str, str]) -> None:
        with server:
            assert len(server.get_sockets()) == 0
            assert len(server.get_addresses()) == 0

    @pytest.mark.usefixtures("start_server")
    def test____socket_property____server_is_running(self, server: StandaloneTCPNetworkServer[str, str]) -> None:
        assert len(server.get_sockets()) > 0
        assert len(server.get_addresses()) > 0


class TestStandaloneUDPNetworkServer(BaseTestStandaloneNetworkServer):
    @pytest.fixture
    @staticmethod
    def server(datagram_protocol: DatagramProtocol[str, str]) -> StandaloneUDPNetworkServer[str, str]:
        return StandaloneUDPNetworkServer("localhost", 0, datagram_protocol, EchoRequestHandler(), "asyncio")

    def test____socket_property____server_is_not_running(self, server: StandaloneUDPNetworkServer[str, str]) -> None:
        with server:
            assert len(server.get_sockets()) == 0
            assert len(server.get_addresses()) == 0

    @pytest.mark.usefixtures("start_server")
    def test____socket_property____server_is_running(self, server: StandaloneUDPNetworkServer[str, str]) -> None:
        assert len(server.get_sockets()) > 0
        assert len(server.get_addresses()) > 0


@PlatformMarkers.skipif_platform_win32
class TestStandaloneUnixStreamServer(BaseTestStandaloneNetworkServer):
    @pytest.fixture
    @staticmethod
    def server(
        unix_socket_path_factory: UnixSocketPathFactory,
        stream_protocol: AnyStreamProtocolType[str, str],
    ) -> StandaloneUnixStreamServer[str, str]:
        return StandaloneUnixStreamServer(unix_socket_path_factory(), stream_protocol, EchoRequestHandler(), "asyncio")

    def test____socket_property____server_is_not_running(self, server: StandaloneUnixStreamServer[str, str]) -> None:
        with server:
            assert len(server.get_sockets()) == 0
            assert len(server.get_addresses()) == 0

    @pytest.mark.usefixtures("start_server")
    def test____socket_property____server_is_running(self, server: StandaloneUnixStreamServer[str, str]) -> None:
        assert len(server.get_sockets()) == 1
        assert len(server.get_addresses()) == 1


@PlatformMarkers.skipif_platform_win32
class TestStandaloneUnixDatagramServer(BaseTestStandaloneNetworkServer):
    @pytest.fixture
    @staticmethod
    def server(
        unix_socket_path_factory: UnixSocketPathFactory,
        datagram_protocol: DatagramProtocol[str, str],
    ) -> StandaloneUnixDatagramServer[str, str]:
        return StandaloneUnixDatagramServer(unix_socket_path_factory(), datagram_protocol, EchoRequestHandler(), "asyncio")

    def test____socket_property____server_is_not_running(self, server: StandaloneUnixDatagramServer[str, str]) -> None:
        with server:
            assert len(server.get_sockets()) == 0
            assert len(server.get_addresses()) == 0

    @pytest.mark.usefixtures("start_server")
    def test____socket_property____server_is_running(self, server: StandaloneUnixDatagramServer[str, str]) -> None:
        assert len(server.get_sockets()) == 1
        assert len(server.get_addresses()) == 1
