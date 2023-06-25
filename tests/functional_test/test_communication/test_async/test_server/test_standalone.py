# -*- coding: utf-8 -*-

from __future__ import annotations

import asyncio
import threading
import time
from typing import AsyncGenerator, Callable, Iterator

from easynetwork.api_async.server.handler import AsyncBaseRequestHandler, AsyncClientInterface
from easynetwork.api_async.server.standalone import (
    AbstractStandaloneNetworkServer,
    StandaloneTCPNetworkServer,
    StandaloneUDPNetworkServer,
)
from easynetwork.exceptions import BaseProtocolParseError
from easynetwork.protocol import DatagramProtocol, StreamProtocol

import pytest


class EchoRequestHandler(AsyncBaseRequestHandler[str, str]):
    async def handle(self, client: AsyncClientInterface[str]) -> AsyncGenerator[None, str]:
        request = yield
        await client.send_packet(request)

    async def bad_request(self, client: AsyncClientInterface[str], exc: BaseProtocolParseError, /) -> None:
        await client.aclose()


class BaseTestStandaloneNetworkServer:
    @pytest.fixture
    @staticmethod
    def start_server(server: AbstractStandaloneNetworkServer) -> Iterator[None]:
        with server:
            is_up_event = threading.Event()
            t = threading.Thread(target=server.serve_forever, kwargs={"is_up_event": is_up_event}, daemon=True)
            t.start()

            if not is_up_event.wait(timeout=1):
                raise TimeoutError("Too long to start")
            assert server.is_serving()

            yield

            server.shutdown()
            assert not server.is_serving()
            t.join()

    def test____is_serving____default_to_False(self, server: AbstractStandaloneNetworkServer) -> None:
        with server:
            assert not server.is_serving()

    def test____shutdown____default_to_noop(self, server: AbstractStandaloneNetworkServer) -> None:
        with server:
            server.shutdown()

    def test____shutdown____while_server_is_running(self, server: AbstractStandaloneNetworkServer) -> None:
        with server:
            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()

            time.sleep(1)
            if not server.is_serving():
                pytest.fail("Timeout error")

            server.shutdown()
            assert not server.is_serving()
            t.join()

    @pytest.mark.usefixtures("start_server")
    def test____server_close____while_server_is_running(self, server: AbstractStandaloneNetworkServer) -> None:
        server.server_close()

    @pytest.mark.usefixtures("start_server")
    def test____serve_forever____error_server_already_running(self, server: AbstractStandaloneNetworkServer) -> None:
        with pytest.raises(RuntimeError):
            server.serve_forever()


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
            None,
            0,
            datagram_protocol,
            EchoRequestHandler(),
            backend_kwargs={"runner_factory": runner_factory},
        )

    def test____socket_property____server_is_not_running(self, server: StandaloneUDPNetworkServer[str, str]) -> None:
        with server:
            assert server.socket is None
            assert server.get_address() is None

    @pytest.mark.usefixtures("start_server")
    def test____socket_property____server_is_running(self, server: StandaloneUDPNetworkServer[str, str]) -> None:
        assert server.socket is not None
        assert server.get_address() is not None
