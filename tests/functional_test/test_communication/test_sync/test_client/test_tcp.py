# -*- coding: Utf-8 -*-

from __future__ import annotations

import socketserver
from concurrent.futures import Future
from socket import AF_INET, IPPROTO_TCP, SHUT_WR, TCP_NODELAY, socket as Socket
from typing import Any, Callable, Iterator

from easynetwork.api_sync.client.tcp import TCPNetworkClient
from easynetwork.exceptions import ClientClosedError, StreamProtocolParseError
from easynetwork.protocol import StreamProtocol
from easynetwork.tools.socket import IPv4SocketAddress, IPv6SocketAddress

import pytest

from .....tools import TimeTest


class TestTCPNetworkClient:
    @pytest.fixture
    @staticmethod
    def server(socket_pair: tuple[Socket, Socket]) -> Socket:
        server = socket_pair[0]
        server.setsockopt(IPPROTO_TCP, TCP_NODELAY, 1)
        return server

    @pytest.fixture
    @staticmethod
    def client(
        socket_pair: tuple[Socket, Socket],
        stream_protocol: StreamProtocol[str, str],
    ) -> Iterator[TCPNetworkClient[str, str]]:
        with TCPNetworkClient(socket_pair[1], stream_protocol, give=False) as client:
            client.socket.setsockopt(IPPROTO_TCP, TCP_NODELAY, 1)
            yield client

    def test____close____double_close(self, client: TCPNetworkClient[str, str]) -> None:
        assert not client.is_closed()
        client.close()
        assert client.is_closed()
        client.close()
        assert client.is_closed()

    def test____send_packet____default(self, client: TCPNetworkClient[str, str], server: Socket) -> None:
        client.send_packet("ABCDEF")
        assert server.recv(1024) == b"ABCDEF\n"

    @pytest.mark.platform_linux  # Windows and macOs raise ConnectionAbortedError but in the 2nd send() call
    def test____send_packet____connection_error____fresh_connection_closed_by_server(
        self,
        client: TCPNetworkClient[str, str],
        server: Socket,
    ) -> None:
        server.close()
        with pytest.raises(ConnectionError):
            client.send_packet("ABCDEF")

    @pytest.mark.platform_linux  # Windows and macOs raise ConnectionAbortedError but in the 2nd send() call
    def test____send_packet____connection_error____after_previous_successful_try(
        self,
        client: TCPNetworkClient[str, str],
        server: Socket,
    ) -> None:
        client.send_packet("ABCDEF")
        assert server.recv(1024) == b"ABCDEF\n"
        server.close()
        with pytest.raises(ConnectionError):
            client.send_packet("ABCDEF")

    def test____send_packet____connection_error____partial_read_then_close(
        self,
        client: TCPNetworkClient[str, str],
        server: Socket,
    ) -> None:
        client.send_packet("ABC")
        assert server.recv(1) == b"A"
        server.close()
        with pytest.raises(ConnectionError):
            client.send_packet("DEF")

    def test____send_packet____closed_client(self, client: TCPNetworkClient[str, str]) -> None:
        client.close()
        with pytest.raises(ClientClosedError):
            client.send_packet("ABCDEF")

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
        with pytest.raises(TimeoutError), TimeTest(0.4, approx=1e-1):
            client.recv_packet(timeout=0.4)
        assert client.recv_packet(timeout=None) == "ABCDEF"

    def test____recv_packet____eof(self, client: TCPNetworkClient[str, str], server: Socket) -> None:
        server.close()
        with pytest.raises(ConnectionAbortedError):
            client.recv_packet()

    def test____recv_packet____client_close_error(self, client: TCPNetworkClient[str, str]) -> None:
        client.close()
        with pytest.raises(ClientClosedError):
            client.recv_packet()

    def test____recv_packet____invalid_data(self, client: TCPNetworkClient[str, str], server: Socket) -> None:
        server.sendall("\u00E9\nvalid\n".encode("latin-1"))
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


class TestTCPNetworkClientConnection:
    class Server(socketserver.TCPServer):
        class RequestHandler(socketserver.StreamRequestHandler):
            def handle(self) -> None:
                data: bytes = self.rfile.readline()
                self.wfile.write(data)

        allow_reuse_address = True

        def __init__(self, server_address: tuple[str, int], socket_family: int) -> None:
            self.address_family = socket_family
            super().__init__(server_address, self.RequestHandler)

    @pytest.fixture(autouse=True)
    @classmethod
    def server(cls, localhost: str, socket_family: int) -> Iterator[socketserver.TCPServer]:
        from threading import Thread

        with cls.Server((localhost, 0), socket_family) as server:
            server_thread = Thread(target=server.serve_forever)
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
        localhost: str,
        remote_address: tuple[str, int],
        stream_protocol: StreamProtocol[str, str],
    ) -> None:
        # Arrange

        # Act & Assert
        with TCPNetworkClient(remote_address, stream_protocol, local_address=(localhost, 0)) as client:
            client.send_packet("Test")
            assert client.recv_packet() == "Test"
