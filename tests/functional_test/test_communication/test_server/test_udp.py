# -*- coding: Utf-8 -*-

from __future__ import annotations

import time
from socket import socket as Socket
from threading import Thread
from typing import Any, Callable, Iterator

from easynetwork.protocol import DatagramProtocol
from easynetwork.server.udp import AbstractUDPNetworkServer
from easynetwork.tools.socket import SocketAddress

import pytest

from ....tools import TimeTest


class MyUDPServer(AbstractUDPNetworkServer[str, str]):
    process_time: float = 0

    def process_request(self, request: str, client_address: SocketAddress) -> None:
        if self.process_time > 0:
            time.sleep(self.process_time)
        self.logger.info("%s sent %r", client_address, request)
        self.send_packet_to(request.upper(), client_address)


class BaseTestServer:
    @pytest.fixture  # DO NOT SET autouse=True
    @staticmethod
    def run_server(server: MyUDPServer) -> Iterator[None]:
        t = Thread(target=server.serve_forever)
        t.start()
        try:
            if not server.wait_for_server_to_be_up(timeout=1):
                raise TimeoutError("server not up")
            yield
            server.shutdown()
        finally:
            t.join()


class TestUDPNetworkServer(BaseTestServer):
    @pytest.fixture
    @staticmethod
    def server_factory(request: Any) -> type[MyUDPServer]:
        return getattr(request, "param", MyUDPServer)

    @pytest.fixture
    @staticmethod
    def server(
        server_factory: type[MyUDPServer],
        socket_family: int,
        localhost: str,
        datagram_protocol: DatagramProtocol[str, str],
    ) -> Iterator[MyUDPServer]:
        with server_factory(
            localhost,
            0,
            datagram_protocol,
            family=socket_family,
        ) as server:
            yield server

    @pytest.fixture
    @staticmethod
    def server_address(server: MyUDPServer) -> SocketAddress:
        address = server.get_address()
        return address

    @pytest.fixture
    @staticmethod
    def client_factory(
        server_address: SocketAddress,
        udp_socket_factory: Callable[[], Socket],
        localhost: str,
    ) -> Callable[[], Socket]:
        def factory() -> Socket:
            sock = udp_socket_factory()
            sock.bind((localhost, 0))
            sock.settimeout(None)
            sock.connect(server_address)
            return sock

        return factory

    def test____server_close____double_close(self, server: MyUDPServer) -> None:
        assert not server.is_closed()
        server.server_close()
        assert server.is_closed()
        server.server_close()
        assert server.is_closed()

    def test____serve_forever____default(self, server: MyUDPServer) -> None:
        assert not server.running()

        t = Thread(target=server.serve_forever, daemon=True)
        t.start()
        if not server.wait_for_server_to_be_up(timeout=1):
            raise TimeoutError("server not up")
        assert server.running()

        server.shutdown()
        assert not server.running()

    @pytest.mark.usefixtures("run_server")
    def test____serve_forever____error_already_running(self, server: MyUDPServer) -> None:
        with pytest.raises(RuntimeError, match=r"^Server is already running$"):
            server.serve_forever()

    def test____serve_forever____error_closed_server(self, server: MyUDPServer) -> None:
        server.server_close()
        with pytest.raises(RuntimeError, match=r"^Closed server"):
            server.serve_forever()

    @pytest.mark.usefixtures("run_server")
    def test____serve_forever____close_during_loop____stop_immediately(self, server: MyUDPServer) -> None:
        assert server.running()
        server.server_close()
        assert not server.running()

    @pytest.mark.usefixtures("run_server")
    def test____serve_forever____handle_request(
        self,
        client_factory: Callable[[], Socket],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level("INFO")
        client: Socket = client_factory()
        address, port = client.getsockname()[:2]

        client.send(b"hello, world.")
        assert client.recv(1024) == b"HELLO, WORLD."

        log_messages = [rec.message for rec in caplog.records]
        assert f"{address}:{port} sent 'hello, world.'" in log_messages

    @pytest.mark.usefixtures("run_server")
    def test____client____bad_request(
        self,
        server: MyUDPServer,
        client_factory: Callable[[], Socket],
    ) -> None:
        bad_request_args: tuple[Any, ...] | None = None

        def bad_request(client_address: SocketAddress, *args: Any) -> None:
            nonlocal bad_request_args

            bad_request_args = args
            server.send_packet_to("wrong encoding man.", client_address)

        server.bad_request = bad_request  # type: ignore[assignment]

        client = client_factory()
        client.send("\u00E9\n".encode("latin-1"))  # StringSerializer does not accept unicode
        assert client.recv(1024) == b"wrong encoding man."
        assert bad_request_args == (
            "deserialization",
            "'ascii' codec can't decode byte 0xe9 in position 0: ordinal not in range(128)",
            None,
        )

    @pytest.mark.usefixtures("run_server")
    def test____client____unexpected_error_during_process(
        self,
        server: MyUDPServer,
        client_factory: Callable[[], Socket],
    ) -> None:
        def process_request(request: str, client_address: SocketAddress) -> None:
            raise Exception("Sorry man!")

        default_error_handler = server.handle_error

        def handle_error(client_address: SocketAddress, exc_info: Callable[[], BaseException | None]) -> None:
            default_error_handler(client_address, exc_info)
            server.send_packet_to(str(exc_info()), client_address)

        server.process_request = process_request  # type: ignore[method-assign]
        server.handle_error = handle_error  # type: ignore[method-assign]

        client = client_factory()
        client.send(b"hello")
        assert client.recv(1024) == b"Sorry man!"


class TestUDPNetworkServerConcurrency(BaseTestServer):
    @pytest.fixture
    @staticmethod
    def socket_family() -> int:  # IPv4 only, we do not want to duplicate these long tests by 2 :)
        from socket import AF_INET

        return AF_INET

    @pytest.fixture
    @staticmethod
    def server_thread_pool_size(request: Any) -> int:
        return getattr(request, "param", 0)

    @pytest.fixture
    @staticmethod
    def server_factory(request: Any) -> type[MyUDPServer]:
        return getattr(request, "param", MyUDPServer)

    @pytest.fixture
    @staticmethod
    def server(
        server_factory: type[MyUDPServer],
        socket_family: int,
        localhost: str,
        datagram_protocol: DatagramProtocol[str, str],
        server_thread_pool_size: int,
    ) -> Iterator[MyUDPServer]:
        with server_factory(
            localhost,
            0,
            datagram_protocol,
            family=socket_family,
            thread_pool_size=server_thread_pool_size,
        ) as server:
            yield server

    @pytest.fixture
    @staticmethod
    def server_address(server: MyUDPServer) -> SocketAddress:
        address = server.get_address()
        return address

    @pytest.fixture
    @staticmethod
    def client_factory(
        server_address: SocketAddress,
        udp_socket_factory: Callable[[], Socket],
        localhost: str,
    ) -> Callable[[], Socket]:
        def factory() -> Socket:
            sock = udp_socket_factory()
            sock.bind((localhost, 0))
            sock.settimeout(None)
            sock.connect(server_address)
            return sock

        return factory

    @pytest.mark.parametrize("server_thread_pool_size", [pytest.param(2, id="thread_pool_size==2")], indirect=True)
    @pytest.mark.usefixtures("run_server")
    def test____serve_forever____concurrent_requests(
        self,
        server: MyUDPServer,
        client_factory: Callable[[], Socket],
    ) -> None:
        client_1 = client_factory()
        client_2 = client_factory()

        server.process_time = 1

        client_1.send(b"hello")
        client_2.send(b"world")
        with TimeTest(1, approx=2e-1):
            assert client_1.recv(1024) == b"HELLO"
            assert client_2.recv(1024) == b"WORLD"
