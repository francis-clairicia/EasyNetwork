# -*- coding: Utf-8 -*-

from __future__ import annotations

import time
from socket import IPPROTO_TCP, TCP_NODELAY, socket as Socket
from threading import Thread
from typing import Any, Callable, Iterator
from weakref import WeakSet

from easynetwork.protocol import StreamProtocol
from easynetwork.sync_def.server.tcp import AbstractTCPNetworkServer, ConnectedClient
from easynetwork.tools.socket import SocketAddress

import pytest

from .....tools import TimeTest


class MyTCPServer(AbstractTCPNetworkServer[str, str]):
    connected_clients: WeakSet[ConnectedClient[str]]

    process_time: float = 0

    def serve_forever(self) -> None:
        self.service_init()
        try:
            return super().serve_forever()
        finally:
            self.service_quit()

    def service_init(self) -> None:
        self.connected_clients = WeakSet()

    def service_quit(self) -> None:
        self.connected_clients.clear()

    def on_connection(self, client: ConnectedClient[str]) -> None:
        super().on_connection(client)
        self.connected_clients.add(client)
        client.send_packet("milk")

    def on_disconnection(self, client: ConnectedClient[str]) -> None:
        self.connected_clients.discard(client)
        super().on_disconnection(client)

    def process_request(self, request: str, client: ConnectedClient[str]) -> None:
        if self.process_time > 0:
            time.sleep(self.process_time)
        self.logger.info("%s sent %r", client.address, request)
        client.send_packet(request.upper())


class BaseTestServer:
    @pytest.fixture  # DO NOT SET autouse=True
    @staticmethod
    def run_server(server: MyTCPServer) -> Iterator[None]:
        t = Thread(target=server.serve_forever)
        t.start()
        try:
            if not server.wait_for_server_to_be_up(timeout=1):
                raise TimeoutError("server not up")
            yield
            server.shutdown()
        finally:
            t.join()


class TestTCPNetworkServer(BaseTestServer):
    @pytest.fixture
    @staticmethod
    def server_factory(request: Any) -> type[MyTCPServer]:
        return getattr(request, "param", MyTCPServer)

    @pytest.fixture
    @staticmethod
    def server(
        server_factory: type[MyTCPServer],
        socket_family: int,
        localhost: str,
        stream_protocol: StreamProtocol[str, str],
    ) -> Iterator[MyTCPServer]:
        with server_factory(localhost, 0, stream_protocol, family=socket_family) as server:
            yield server

    @pytest.fixture
    @staticmethod
    def server_address(server: MyTCPServer) -> SocketAddress:
        address = server.get_address()
        return address

    @pytest.fixture
    @staticmethod
    def client_factory(server_address: SocketAddress, tcp_socket_factory: Callable[[], Socket]) -> Callable[[], Socket]:
        def factory() -> Socket:
            sock = tcp_socket_factory()
            sock.settimeout(None)
            sock.connect(server_address)
            with sock.makefile("rb") as io:
                assert io.readline() == b"milk\n"
            return sock

        return factory

    def test____server_close____double_close(self, server: MyTCPServer) -> None:
        assert not server.is_closed()
        server.server_close()
        assert server.is_closed()
        server.server_close()
        assert server.is_closed()

    def test____serve_forever____default(self, server: MyTCPServer) -> None:
        assert not server.running()

        t = Thread(target=server.serve_forever, daemon=True)
        t.start()
        if not server.wait_for_server_to_be_up(timeout=1):
            raise TimeoutError("server not up")
        assert server.running()

        server.shutdown()
        assert not server.running()

    @pytest.mark.usefixtures("run_server")
    def test____serve_forever____error_already_running(self, server: MyTCPServer) -> None:
        with pytest.raises(RuntimeError, match=r"^Server is already running$"):
            server.serve_forever()

    def test____serve_forever____error_closed_server(self, server: MyTCPServer) -> None:
        server.server_close()
        with pytest.raises(RuntimeError, match=r"^Closed server"):
            server.serve_forever()

    @pytest.mark.usefixtures("run_server")
    def test____serve_forever____client_connection_and_disconnection(
        self,
        server: MyTCPServer,
        client_factory: Callable[[], Socket],
    ) -> None:
        client: Socket = client_factory()

        while len(server.connected_clients) == 0:
            time.sleep(0.1)

        assert client.getsockname() in [c.address for c in server.connected_clients]

        client.sendall(b"hello, world.\n")
        assert client.recv(1024) == b"HELLO, WORLD.\n"

        client.close()

        while len(server.connected_clients) > 0:
            time.sleep(0.1)

    @pytest.mark.usefixtures("run_server")
    def test____serve_forever____disable_nagle_algorithm(
        self,
        server: MyTCPServer,
        client_factory: Callable[[], Socket],
    ) -> None:
        _ = client_factory()

        while len(server.connected_clients) == 0:
            time.sleep(0.1)

        connected_client: ConnectedClient[str] = list(server.connected_clients)[0]

        tcp_nodelay_state: int = connected_client.socket.getsockopt(IPPROTO_TCP, TCP_NODELAY)

        # Do not test with '== 1', on macOS it will return 4
        # (c.f. https://stackoverflow.com/a/31835137)
        assert tcp_nodelay_state != 0

    @pytest.mark.usefixtures("run_server")
    def test____serve_forever____close_during_loop____stop_immediately_without_clients(
        self,
        server: MyTCPServer,
    ) -> None:
        assert server.running()
        server.server_close()
        time.sleep(0.3)
        assert not server.running()

    @pytest.mark.usefixtures("run_server")
    def test____serve_forever____close_during_loop____continue_until_all_clients_are_gone(
        self,
        server: MyTCPServer,
        client_factory: Callable[[], Socket],
    ) -> None:
        assert server.running()

        client = client_factory()

        server.server_close()
        time.sleep(0.3)
        assert server.running()

        client.sendall(b"hello\n")
        assert client.recv(1024) == b"HELLO\n"
        client.sendall(b"world!\n")
        assert client.recv(1024) == b"WORLD!\n"
        assert server.running()

        client.close()
        time.sleep(0.3)
        assert not server.running()

    @pytest.mark.usefixtures("run_server")
    def test____client____partial_request(
        self,
        client_factory: Callable[[], Socket],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level("INFO")
        client = client_factory()
        address, port = client.getsockname()[:2]
        client.sendall(b"hello")
        time.sleep(0.1)
        client.sendall(b", world!\n")
        assert client.recv(1024) == b"HELLO, WORLD!\n"
        log_messages = [rec.message for rec in caplog.records]
        assert f"{address}:{port} sent 'hello, world!'" in log_messages

    @pytest.mark.usefixtures("run_server")
    def test____client____several_request_at_same_time(
        self,
        client_factory: Callable[[], Socket],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level("INFO")
        client = client_factory()
        address, port = client.getsockname()[:2]
        client.sendall(b"hello\nworld\n")
        assert client.recv(6) == b"HELLO\n"
        assert client.recv(6) == b"WORLD\n"
        log_messages = [rec.message for rec in caplog.records]
        assert f"{address}:{port} sent 'hello'" in log_messages
        assert f"{address}:{port} sent 'world'" in log_messages

    @pytest.mark.usefixtures("run_server")
    def test____client____bad_request(
        self,
        server: MyTCPServer,
        client_factory: Callable[[], Socket],
    ) -> None:
        bad_request_args: tuple[Any, ...] | None = None

        def bad_request(client: ConnectedClient[str], *args: Any) -> None:
            nonlocal bad_request_args

            bad_request_args = args
            client.send_packet("wrong encoding man.")

        server.bad_request = bad_request  # type: ignore[assignment]

        client = client_factory()
        client.sendall("\u00E9\n".encode("latin-1"))  # StringSerializer does not accept unicode
        assert client.recv(1024) == b"wrong encoding man.\n"
        assert bad_request_args == (
            "deserialization",
            "'ascii' codec can't decode byte 0xe9 in position 0: ordinal not in range(128)",
            None,
        )

    @pytest.mark.usefixtures("run_server")
    def test____client____unexpected_error_during_process(
        self,
        server: MyTCPServer,
        client_factory: Callable[[], Socket],
    ) -> None:
        def process_request(request: str, client: ConnectedClient[str]) -> None:
            raise Exception("Sorry man!")

        default_error_handler = server.handle_error

        def handle_error(client: ConnectedClient[str], exc_info: Callable[[], BaseException | None]) -> None:
            assert not client.is_closed()
            default_error_handler(client, exc_info)
            client.send_packet(str(exc_info()))

        server.process_request = process_request  # type: ignore[method-assign]
        server.handle_error = handle_error  # type: ignore[method-assign]

        client = client_factory()
        client.sendall(b"hello\n")
        assert client.recv(1024) == b"Sorry man!\n"


@pytest.mark.slow
class TestTCPNetworkServerConcurrency(BaseTestServer):
    @pytest.fixture
    @staticmethod
    def socket_family() -> int:  # IPv4 only, we do not want to duplicate these long tests by 2 :)
        from socket import AF_INET

        return AF_INET

    @pytest.fixture
    @staticmethod
    def server_factory(request: Any) -> type[MyTCPServer]:
        return getattr(request, "param", MyTCPServer)

    @pytest.fixture
    @staticmethod
    def server_thread_pool_size(request: Any) -> int:
        return getattr(request, "param", 0)

    @pytest.fixture
    @staticmethod
    def server(
        server_factory: type[MyTCPServer],
        socket_family: int,
        localhost: str,
        stream_protocol: StreamProtocol[str, str],
        server_thread_pool_size: int,
    ) -> Iterator[MyTCPServer]:
        with server_factory(
            localhost,
            0,
            stream_protocol,
            family=socket_family,
            thread_pool_size=server_thread_pool_size,
        ) as server:
            yield server

    @pytest.fixture
    @staticmethod
    def server_address(server: MyTCPServer) -> SocketAddress:
        address = server.get_address()
        return address

    @pytest.fixture
    @staticmethod
    def client_factory(server_address: SocketAddress, tcp_socket_factory: Callable[[], Socket]) -> Callable[[], Socket]:
        def client_factory() -> Socket:
            sock = tcp_socket_factory()
            sock.settimeout(None)
            sock.connect(server_address)
            assert sock.recv(5) == b"milk\n"
            return sock

        return client_factory

    @pytest.mark.parametrize("server_thread_pool_size", [pytest.param(2, id="thread_pool_size==2")], indirect=True)
    @pytest.mark.usefixtures("run_server")
    def test____serve_forever____concurrent_requests(
        self,
        server: MyTCPServer,
        client_factory: Callable[[], Socket],
    ) -> None:
        client_1 = client_factory()
        client_2 = client_factory()

        server.process_time = 1

        client_1.sendall(b"hello\n")
        client_2.sendall(b"world\n")
        with TimeTest(1, approx=2e-1):
            assert client_1.recv(1024) == b"HELLO\n"
            assert client_2.recv(1024) == b"WORLD\n"

    @pytest.mark.parametrize("server_thread_pool_size", [pytest.param(3, id="thread_pool_size==3")], indirect=True)
    @pytest.mark.usefixtures("run_server")
    def test____serve_forever____do_not_put_same_client_for_two_or_more_requests_in_pool(
        self,
        server: MyTCPServer,
        client_factory: Callable[[], Socket],
    ) -> None:
        client_1 = client_factory()
        client_2 = client_factory()

        messages = [b"hello\n", b"world\n", b"smash\n"]

        server.process_time = 1

        for msg in messages:
            client_1.sendall(msg)
            client_2.sendall(msg)
        with TimeTest(3, approx=5e-1):
            for msg in messages:
                msg = msg.upper()
                assert client_1.recv(1024) == msg
                assert client_2.recv(1024) == msg
