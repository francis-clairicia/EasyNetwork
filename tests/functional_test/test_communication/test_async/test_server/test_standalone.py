# -*- coding: Utf-8 -*-

from __future__ import annotations

import asyncio
import threading
import time
from typing import AsyncGenerator, Callable

from easynetwork.api_async.server.handler import AsyncBaseRequestHandler, AsyncClientInterface
from easynetwork.api_async.server.standalone import AbstractStandaloneNetworkServer
from easynetwork.api_async.server.tcp import AsyncTCPNetworkServer
from easynetwork.api_async.server.udp import AsyncUDPNetworkServer
from easynetwork.protocol import DatagramProtocol, StreamProtocol
from easynetwork_asyncio.server import StandaloneTCPNetworkServer, StandaloneUDPNetworkServer

import pytest


class EchoRequestHandler(AsyncBaseRequestHandler[str, str]):
    async def handle(self, client: AsyncClientInterface[str]) -> AsyncGenerator[None, str]:
        request = yield
        await client.send_packet(request)


class BaseTestStandaloneNetworkServer:
    def test____is_serving____default_to_False(self, server: AbstractStandaloneNetworkServer) -> None:
        with server:
            assert not server.is_serving()

    def test____shutdown____default_to_noop(self, server: AbstractStandaloneNetworkServer) -> None:
        with server:
            server.shutdown()

    def test____shutdown____stop_serve_forever(self, server: AbstractStandaloneNetworkServer) -> None:
        with server:
            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()

            time.sleep(0.1)
            assert server.is_serving()

            server.shutdown()
            t.join()
            assert not server.is_serving()

    def test____server_close____while_server_is_running(self, server: AbstractStandaloneNetworkServer) -> None:
        with server:
            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()

            time.sleep(0.1)
            server.server_close()

            server.shutdown()
            t.join()

    def test____serve_forever____error_server_already_running(self, server: AbstractStandaloneNetworkServer) -> None:
        with server:
            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()

            time.sleep(0.1)
            with pytest.raises(RuntimeError):
                server.serve_forever()

            server.shutdown()
            t.join()


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
            AsyncTCPNetworkServer(None, 0, stream_protocol, EchoRequestHandler(), backend="asyncio"),
            runner_factory=runner_factory,
        )

    def test____stop_listening____default_to_noop(self, server: StandaloneTCPNetworkServer[str, str]) -> None:
        with server:
            server.stop_listening()

    def test____stop_listening____stop_accepting_new_connection(self, server: StandaloneTCPNetworkServer[str, str]) -> None:
        with server:
            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()

            time.sleep(0.1)
            assert server.is_serving()

            server.stop_listening()
            assert not server.is_serving()

            server.shutdown()
            t.join()


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
            AsyncUDPNetworkServer(None, 0, datagram_protocol, EchoRequestHandler(), backend="asyncio"),
            runner_factory=runner_factory,
        )
