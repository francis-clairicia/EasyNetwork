from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import AsyncGenerator, Callable, Iterator

from easynetwork.api_async.server.handler import (
    AsyncBaseClientInterface,
    AsyncDatagramRequestHandler,
    AsyncStreamClient,
    AsyncStreamRequestHandler,
)
from easynetwork.api_sync.server.abc import AbstractNetworkServer
from easynetwork.api_sync.server.tcp import StandaloneTCPNetworkServer
from easynetwork.api_sync.server.thread import NetworkServerThread
from easynetwork.api_sync.server.udp import StandaloneUDPNetworkServer
from easynetwork.exceptions import BaseProtocolParseError, ServerAlreadyRunning, ServerClosedError
from easynetwork.protocol import DatagramProtocol, StreamProtocol

import pytest


class EchoRequestHandler(AsyncStreamRequestHandler[str, str], AsyncDatagramRequestHandler[str, str]):
    async def handle(self, client: AsyncBaseClientInterface[str]) -> AsyncGenerator[None, str]:
        request = yield
        await client.send_packet(request)

    async def bad_request(self, client: AsyncBaseClientInterface[str], exc: BaseProtocolParseError, /) -> None:
        if isinstance(client, AsyncStreamClient):
            await client.aclose()


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
    def test____shutdown____while_server_is_running(self, server: AbstractNetworkServer) -> None:
        assert server.is_serving()

        server.shutdown()
        assert not server.is_serving()

    def test____server_close____idempotent(self, server: AbstractNetworkServer) -> None:
        server.server_close()
        server.server_close()
        server.server_close()

    @pytest.mark.usefixtures("start_server")
    def test____server_close____while_server_is_running(self, server: AbstractNetworkServer) -> None:
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

    def test____server_thread____several_join(
        self,
        start_server: NetworkServerThread,
    ) -> None:
        start_server.join()
        start_server.join()


def custom_asyncio_runner() -> asyncio.Runner:
    return asyncio.Runner(loop_factory=asyncio.new_event_loop)


class TestStandaloneTCPNetworkServer(BaseTestStandaloneNetworkServer):
    @pytest.fixture(params=[None, custom_asyncio_runner])
    @staticmethod
    def runner_factory(request: pytest.FixtureRequest) -> Callable[[], asyncio.Runner] | None:
        return getattr(request, "param", None)

    @pytest.fixture
    @staticmethod
    def server(
        stream_protocol: StreamProtocol[str, str],
        runner_factory: Callable[[], asyncio.Runner] | None,
    ) -> StandaloneTCPNetworkServer[str, str]:
        return StandaloneTCPNetworkServer(
            None,
            0,
            stream_protocol,
            EchoRequestHandler(),
            backend_kwargs={"runner_factory": runner_factory},
        )

    def test____dunder_init____invalid_backend(self, stream_protocol: StreamProtocol[str, str]) -> None:
        with pytest.raises(ValueError, match=r"^You must explicitly give a backend name or instance$"):
            _ = StandaloneTCPNetworkServer(
                None,
                0,
                stream_protocol,
                EchoRequestHandler(),
                backend=None,  # type: ignore[arg-type]
            )

    @pytest.mark.parametrize("runner_factory", [None], indirect=True)
    def test____serve_forever____serve_several_times(self, server: StandaloneTCPNetworkServer[str, str]) -> None:
        with server:
            for _ in range(3):
                assert not server.is_serving()
                assert not server.get_addresses()

                server_thread = NetworkServerThread(server, daemon=True)
                server_thread.start()
                try:
                    assert server.is_serving()
                    assert len(server.get_addresses()) > 0
                    time.sleep(0.5)
                finally:
                    server_thread.join()

    def test____stop_listening____default_to_noop(self, server: StandaloneTCPNetworkServer[str, str]) -> None:
        with server:
            assert not server.sockets
            assert not server.get_addresses()
            server.stop_listening()

    @pytest.mark.usefixtures("start_server")
    def test____stop_listening____stop_accepting_new_connection(self, server: StandaloneTCPNetworkServer[str, str]) -> None:
        assert server.is_serving()
        assert len(server.sockets) > 0
        assert len(server.get_addresses()) > 0

        server.stop_listening()
        assert not server.is_serving()
        assert len(server.sockets) > 0  # Sockets are closed, but always available until server_close() call
        assert len(server.get_addresses()) == 0

    def test____logger_property____exposed(self, server: StandaloneTCPNetworkServer[str, str]) -> None:
        assert server.logger is server._server.logger


class TestStandaloneUDPNetworkServer(BaseTestStandaloneNetworkServer):
    @pytest.fixture(params=[None, custom_asyncio_runner])
    @staticmethod
    def runner_factory(request: pytest.FixtureRequest) -> Callable[[], asyncio.Runner] | None:
        return getattr(request, "param", None)

    @pytest.fixture
    @staticmethod
    def server(
        datagram_protocol: DatagramProtocol[str, str],
        runner_factory: Callable[[], asyncio.Runner] | None,
    ) -> StandaloneUDPNetworkServer[str, str]:
        return StandaloneUDPNetworkServer(
            "localhost",
            0,
            datagram_protocol,
            EchoRequestHandler(),
            backend_kwargs={"runner_factory": runner_factory},
        )

    def test____dunder_init____invalid_backend(self, datagram_protocol: DatagramProtocol[str, str]) -> None:
        with pytest.raises(ValueError, match=r"^You must explicitly give a backend name or instance$"):
            _ = StandaloneUDPNetworkServer(
                "localhost",
                0,
                datagram_protocol,
                EchoRequestHandler(),
                backend=None,  # type: ignore[arg-type]
            )

    @pytest.mark.parametrize("runner_factory", [None], indirect=True)
    def test____serve_forever____serve_several_times(self, server: StandaloneUDPNetworkServer[str, str]) -> None:
        with server:
            for _ in range(3):
                assert not server.is_serving()
                assert server.get_address() is None

                server_thread = NetworkServerThread(server, daemon=True)
                server_thread.start()
                try:
                    assert server.is_serving()
                    assert server.get_address() is not None
                    time.sleep(0.5)
                finally:
                    server_thread.join()

    def test____socket_property____server_is_not_running(self, server: StandaloneUDPNetworkServer[str, str]) -> None:
        with server:
            assert server.socket is None
            assert server.get_address() is None

    @pytest.mark.usefixtures("start_server")
    def test____socket_property____server_is_running(self, server: StandaloneUDPNetworkServer[str, str]) -> None:
        assert server.socket is not None
        assert server.get_address() is not None

    def test____logger_property____exposed(self, server: StandaloneUDPNetworkServer[str, str]) -> None:
        assert server.logger is server._server.logger
