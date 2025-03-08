from __future__ import annotations

import socketserver
import ssl
import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future
from socket import AF_INET, IPPROTO_TCP, SHUT_WR, TCP_NODELAY, socket as Socket
from typing import Any

from easynetwork.clients.tcp import TCPNetworkClient
from easynetwork.exceptions import ClientClosedError, StreamProtocolParseError
from easynetwork.lowlevel.socket import IPv4SocketAddress, IPv6SocketAddress
from easynetwork.protocol import AnyStreamProtocolType

import pytest

from .....tools import TimeTest
from .common import readline


@pytest.mark.usefixtures("simulate_no_ssl_module")
@pytest.mark.flaky(retries=3, delay=0.1)
class TestTCPNetworkClient:
    @pytest.fixture
    @staticmethod
    def server(inet_socket_pair: tuple[Socket, Socket]) -> Socket:
        server = inet_socket_pair[0]
        server.setsockopt(IPPROTO_TCP, TCP_NODELAY, 1)
        return server

    @pytest.fixture
    @staticmethod
    def client(
        inet_socket_pair: tuple[Socket, Socket],
        stream_protocol: AnyStreamProtocolType[str, str],
    ) -> Iterator[TCPNetworkClient[str, str]]:
        with TCPNetworkClient(inet_socket_pair[1], stream_protocol) as client:
            yield client

    def test____close____idempotent(self, client: TCPNetworkClient[str, str]) -> None:
        assert not client.is_closed()
        client.close()
        assert client.is_closed()
        client.close()
        assert client.is_closed()

    def test____send_packet____default(self, client: TCPNetworkClient[str, str], server: Socket) -> None:
        client.send_packet("ABCDEF")
        assert readline(server) == b"ABCDEF\n"

    def test____send_packet____connection_error____fresh_connection_closed_by_server(
        self,
        client: TCPNetworkClient[str, str],
        server: Socket,
    ) -> None:
        server.close()
        with pytest.raises(ConnectionAbortedError):
            for _ in range(3):  # Windows and macOS catch the issue after several send()
                client.send_packet("ABCDEF")
                time.sleep(0.01)

    def test____send_packet____connection_error____after_previous_successful_try(
        self,
        client: TCPNetworkClient[str, str],
        server: Socket,
    ) -> None:
        client.send_packet("ABCDEF")
        assert readline(server) == b"ABCDEF\n"
        server.close()
        with pytest.raises(ConnectionAbortedError):
            for _ in range(3):  # Windows and macOS catch the issue after several send()
                client.send_packet("ABCDEF")
                time.sleep(0.01)

    def test____send_packet____connection_error____partial_read_then_close(
        self,
        client: TCPNetworkClient[str, str],
        server: Socket,
    ) -> None:
        client.send_packet("ABC")
        assert server.recv(1) == b"A"
        server.close()
        with pytest.raises(ConnectionAbortedError):
            for _ in range(3):  # Windows and macOS catch the issue after several send()
                client.send_packet("DEF")
                time.sleep(0.01)

    def test____send_packet____closed_client(self, client: TCPNetworkClient[str, str]) -> None:
        client.close()
        with pytest.raises(ClientClosedError):
            client.send_packet("ABCDEF")

    def test____send_eof____close_write_stream(
        self,
        client: TCPNetworkClient[str, str],
        server: Socket,
    ) -> None:
        client.send_eof()
        assert readline(server) == b""
        with pytest.raises(RuntimeError):
            client.send_packet("ABC")

        server.sendall(b"ABCDEF\n")
        assert client.recv_packet() == "ABCDEF"

    def test____send_eof____closed_client(
        self,
        client: TCPNetworkClient[str, str],
    ) -> None:
        client.close()
        client.send_eof()

    def test____send_eof____idempotent(
        self,
        client: TCPNetworkClient[str, str],
        server: Socket,
    ) -> None:
        client.send_eof()
        assert readline(server) == b""
        client.send_eof()
        client.send_eof()

    def test____recv_packet____default(self, client: TCPNetworkClient[str, str], server: Socket) -> None:
        server.sendall(b"ABCDEF\n")
        assert client.recv_packet() == "ABCDEF"

    def test____recv_packet____partial(
        self,
        client: TCPNetworkClient[str, str],
        server: Socket,
        schedule_call_in_thread: Callable[[float, Callable[[], Any]], None],
    ) -> None:
        server.sendall(b"ABC")
        schedule_call_in_thread(0.1, lambda: server.sendall(b"DEF\n"))
        assert client.recv_packet() == "ABCDEF"

    def test____recv_packet____buffer(self, client: TCPNetworkClient[str, str], server: Socket) -> None:
        server.sendall(b"A\nB\nC\nD\n")
        assert client.recv_packet() == "A"
        assert client.recv_packet(timeout=0) == "B"
        assert client.recv_packet(timeout=0) == "C"
        assert client.recv_packet(timeout=0) == "D"
        server.sendall(b"E\nF\nG\nH\nI")
        assert client.recv_packet() == "E"
        assert client.recv_packet(timeout=0) == "F"
        assert client.recv_packet(timeout=0) == "G"
        assert client.recv_packet(timeout=0) == "H"
        with pytest.raises(TimeoutError):
            client.recv_packet(timeout=0)
        server.sendall(b"J\n")
        assert client.recv_packet() == "IJ"

    def test____recv_packet____timeout(
        self,
        client: TCPNetworkClient[str, str],
        server: Socket,
        schedule_call_in_thread_with_future: Callable[[float, Callable[[], Any]], Future[Any]],
    ) -> None:
        # Case 1: Default timeout behaviour
        server.sendall(b"ABC")
        schedule_call_in_thread_with_future(0.1, lambda: server.sendall(b"DEF\n"))
        with pytest.raises(TimeoutError):
            client.recv_packet(timeout=0)
        assert client.recv_packet(timeout=None) == "ABCDEF"

        # Case 2: Several recv() within timeout
        def schedule_send(chunks: list[bytes]) -> None:
            f = schedule_call_in_thread_with_future(0.1, lambda: server.sendall(chunks.pop(0)))
            if chunks:
                f.add_done_callback(lambda _: schedule_send(chunks))

        schedule_send([b"A", b"B", b"C", b"D", b"E", b"F\n"])
        with TimeTest(0.4, approx=2e-1), pytest.raises(TimeoutError):
            client.recv_packet(timeout=0.4)
        assert client.recv_packet(timeout=None) == "ABCDEF"

    def test____recv_packet____eof____closed_remote(self, client: TCPNetworkClient[str, str], server: Socket) -> None:
        server.close()
        with pytest.raises(ConnectionAbortedError):
            client.recv_packet()

    def test____recv_packet____eof____shutdown_write_only(self, client: TCPNetworkClient[str, str], server: Socket) -> None:
        server.shutdown(SHUT_WR)
        with pytest.raises(ConnectionAbortedError):
            client.recv_packet()

        client.send_packet("ABCDEF")
        assert readline(server) == b"ABCDEF\n"

    def test____recv_packet____client_close_error(self, client: TCPNetworkClient[str, str]) -> None:
        client.close()
        with pytest.raises(ClientClosedError):
            client.recv_packet()

    def test____recv_packet____invalid_data(self, client: TCPNetworkClient[str, str], server: Socket) -> None:
        server.sendall("\u00e9\nvalid\n".encode("latin-1"))
        with pytest.raises(StreamProtocolParseError):
            client.recv_packet()
        assert client.recv_packet() == "valid"

    def test____iter_received_packets____yields_available_packets_until_timeout(
        self,
        client: TCPNetworkClient[str, str],
        server: Socket,
    ) -> None:
        server.sendall(b"A\nB\nC\nD\nE\nF\n")
        assert list(client.iter_received_packets(timeout=1)) == ["A", "B", "C", "D", "E", "F"]

    def test____iter_received_packets____yields_available_packets_until_eof(
        self,
        client: TCPNetworkClient[str, str],
        server: Socket,
    ) -> None:
        server.sendall(b"A\nB\nC\nD\nE\nF")
        server.shutdown(SHUT_WR)
        server.close()
        assert list(client.iter_received_packets(timeout=None)) == ["A", "B", "C", "D", "E"]

    def test____fileno____consistency(self, client: TCPNetworkClient[str, str]) -> None:
        assert client.fileno() == client.socket.fileno()

    def test____fileno____closed_client(self, client: TCPNetworkClient[str, str]) -> None:
        client.close()
        assert client.fileno() == -1

    def test____get_local_address____consistency(self, socket_family: int, client: TCPNetworkClient[str, str]) -> None:
        address = client.get_local_address()
        if socket_family == AF_INET:
            assert isinstance(address, IPv4SocketAddress)
        else:
            assert isinstance(address, IPv6SocketAddress)
        assert address == client.socket.getsockname()

    def test____get_remote_address____consistency(self, socket_family: int, client: TCPNetworkClient[str, str]) -> None:
        address = client.get_remote_address()
        if socket_family == AF_INET:
            assert isinstance(address, IPv4SocketAddress)
        else:
            assert isinstance(address, IPv6SocketAddress)
        assert address == client.socket.getpeername()


class TCPServer(socketserver.TCPServer):
    class RequestHandler(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            data: bytes = self.rfile.readline()
            if data:
                self.wfile.write(data)

    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        socket_family: int,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self.address_family = socket_family
        super().__init__(server_address, self.RequestHandler)
        self.ssl_context: ssl.SSLContext | None = ssl_context

    def get_request(self) -> tuple[Socket, Any]:
        socket, client_address = super().get_request()

        if self.ssl_context:
            socket = self.ssl_context.wrap_socket(socket, server_side=True, do_handshake_on_connect=True)

        return socket, client_address


@pytest.mark.usefixtures("simulate_no_ssl_module")
class TestTCPNetworkClientConnection:
    @pytest.fixture(autouse=True)
    @classmethod
    def server(cls, localhost_ip: str, socket_family: int) -> Iterator[socketserver.TCPServer]:
        from threading import Thread

        with TCPServer((localhost_ip, 0), socket_family) as server:
            server_thread = Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            yield server
            server.shutdown()
            server_thread.join()

    @pytest.fixture
    @staticmethod
    def remote_address(server: socketserver.TCPServer) -> tuple[str, int]:
        return server.server_address[:2]  # type: ignore[return-value]

    def test____dunder_init____connect_to_server(
        self,
        remote_address: tuple[str, int],
        stream_protocol: AnyStreamProtocolType[str, str],
    ) -> None:
        with TCPNetworkClient(remote_address, stream_protocol) as client:
            client.send_packet("Test")
            assert client.recv_packet() == "Test"

    def test____dunder_init____with_local_address(
        self,
        localhost_ip: str,
        remote_address: tuple[str, int],
        stream_protocol: AnyStreamProtocolType[str, str],
    ) -> None:
        with TCPNetworkClient(remote_address, stream_protocol, local_address=(localhost_ip, 0)) as client:
            client.send_packet("Test")
            assert client.recv_packet() == "Test"


class TestSSLOverTCPNetworkClient:
    @pytest.fixture(autouse=True)
    @classmethod
    def server(
        cls,
        localhost_ip: str,
        socket_family: int,
        server_ssl_context: ssl.SSLContext | None,
    ) -> Iterator[socketserver.TCPServer]:
        from threading import Thread

        if server_ssl_context is None:
            pytest.skip("trustme is not installed")

        with TCPServer((localhost_ip, 0), socket_family, ssl_context=server_ssl_context) as server:
            server_thread = Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            yield server
            server.shutdown()
            server_thread.join()

    @pytest.fixture
    @staticmethod
    def remote_address(server: socketserver.TCPServer) -> tuple[str, int]:
        return server.server_address[:2]  # type: ignore[return-value]

    def test____dunder_init____handshake_and_shutdown(
        self,
        remote_address: tuple[str, int],
        stream_protocol: AnyStreamProtocolType[str, str],
        client_ssl_context: ssl.SSLContext,
    ) -> None:
        # Arrange

        # Act & Assert
        with TCPNetworkClient(
            remote_address,
            stream_protocol,
            ssl=client_ssl_context,
            server_hostname="test.example.com",
        ) as client:
            client.send_packet("Test")
            assert client.recv_packet() == "Test"

    def test____dunder_init____use_default_context(
        self,
        remote_address: tuple[str, int],
        stream_protocol: AnyStreamProtocolType[str, str],
        client_ssl_context: ssl.SSLContext,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Arrange
        monkeypatch.setattr(ssl, "create_default_context", lambda *args, **kwargs: client_ssl_context)

        # Act & Assert
        with TCPNetworkClient(
            remote_address,
            stream_protocol,
            ssl=True,
            server_hostname="test.example.com",
        ) as client:
            client.send_packet("Test")
            assert client.recv_packet() == "Test"

    def test____dunder_init____use_default_context____disable_hostname_check(
        self,
        remote_address: tuple[str, int],
        stream_protocol: AnyStreamProtocolType[str, str],
        client_ssl_context: ssl.SSLContext,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Arrange
        check_hostname_by_default: bool = client_ssl_context.check_hostname
        assert check_hostname_by_default
        monkeypatch.setattr(ssl, "create_default_context", lambda *args, **kwargs: client_ssl_context)

        # Act & Assert
        with TCPNetworkClient(
            remote_address,
            stream_protocol,
            ssl=True,
            server_hostname="",
        ) as client:
            assert not client_ssl_context.check_hostname  # It must be set to False if server_hostname is an empty string
            client.send_packet("Test")
            assert client.recv_packet() == "Test"

    @pytest.mark.usefixtures("simulate_no_ssl_module")
    def test____dunder_init____no_ssl_module(
        self,
        remote_address: tuple[str, int],
        stream_protocol: AnyStreamProtocolType[str, str],
        client_ssl_context: ssl.SSLContext,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(RuntimeError, match=r"^stdlib ssl module not available$"):
            _ = TCPNetworkClient(
                remote_address,
                stream_protocol,
                ssl=client_ssl_context,
                server_hostname="test.example.com",
            )

    def test____send_eof____not_supported(
        self,
        remote_address: tuple[str, int],
        stream_protocol: AnyStreamProtocolType[str, str],
        client_ssl_context: ssl.SSLContext,
    ) -> None:
        # Arrange

        # Act & Assert
        with TCPNetworkClient(
            remote_address,
            stream_protocol,
            ssl=client_ssl_context,
            server_hostname="test.example.com",
        ) as client:
            with pytest.raises(NotImplementedError):
                client.send_eof()

            client.send_packet("Test")
            assert client.recv_packet() == "Test"
