from __future__ import annotations

import socketserver
from collections.abc import Callable, Iterator
from socket import AF_INET, socket as Socket
from typing import Any

from easynetwork.clients.udp import UDPNetworkClient
from easynetwork.exceptions import ClientClosedError, DatagramProtocolParseError
from easynetwork.lowlevel.socket import IPv4SocketAddress, IPv6SocketAddress
from easynetwork.protocol import DatagramProtocol

import pytest

from .....tools import PlatformMarkers


@pytest.fixture
def udp_socket_factory(udp_socket_factory: Callable[[], Socket], localhost_ip: str) -> Callable[[], Socket]:

    def bound_udp_socket_factory() -> Socket:
        sock = udp_socket_factory()
        sock.bind((localhost_ip, 0))
        return sock

    return bound_udp_socket_factory


@pytest.mark.flaky(retries=3, delay=0.1)
class TestUDPNetworkClient:
    @pytest.fixture
    @staticmethod
    def server(udp_socket_factory: Callable[[], Socket]) -> Socket:
        return udp_socket_factory()

    @pytest.fixture
    @staticmethod
    def client(
        server: Socket,
        udp_socket_factory: Callable[[], Socket],
        datagram_protocol: DatagramProtocol[str, str],
    ) -> Iterator[UDPNetworkClient[str, str]]:
        address: tuple[str, int] = server.getsockname()[:2]
        socket = udp_socket_factory()
        socket.connect(address)

        with UDPNetworkClient(socket, datagram_protocol) as client:
            yield client

    def test____close____idempotent(self, client: UDPNetworkClient[str, str]) -> None:
        assert not client.is_closed()
        client.close()
        assert client.is_closed()
        client.close()
        assert client.is_closed()

    def test____send_packet____default(self, client: UDPNetworkClient[str, str], server: Socket) -> None:
        client.send_packet("ABCDEF")
        assert server.recvfrom(1024) == (b"ABCDEF", client.get_local_address())

    @PlatformMarkers.runs_only_on_platform("linux", "Windows, MacOS and BSD-like do not raise error")
    def test____send_packet____connection_refused(self, client: UDPNetworkClient[str, str], server: Socket) -> None:
        server.close()
        with pytest.raises(ConnectionRefusedError):
            client.send_packet("ABCDEF")

    @PlatformMarkers.runs_only_on_platform("linux", "Windows, MacOS and BSD-like do not raise error")
    def test____send_packet____connection_refused____after_previous_successful_try(
        self,
        client: UDPNetworkClient[str, str],
        server: Socket,
    ) -> None:
        client.send_packet("ABC")
        assert server.recvfrom(1024) == (b"ABC", client.get_local_address())
        server.close()
        with pytest.raises(ConnectionRefusedError):
            client.send_packet("DEF")

    def test____send_packet____closed_client(self, client: UDPNetworkClient[str, str]) -> None:
        client.close()
        with pytest.raises(ClientClosedError):
            client.send_packet("ABCDEF")

    def test____recv_packet____default(self, client: UDPNetworkClient[str, str], server: Socket) -> None:
        server.sendto(b"ABCDEF", client.get_local_address())
        assert client.recv_packet() == "ABCDEF"

    def test____recv_packet____timeout(
        self,
        client: UDPNetworkClient[str, str],
        server: Socket,
        schedule_call_in_thread: Callable[[float, Callable[[], Any]], None],
    ) -> None:
        schedule_call_in_thread(0.1, lambda: server.sendto(b"ABCDEF", client.get_local_address()))
        with pytest.raises(TimeoutError):
            client.recv_packet(timeout=0)
        assert client.recv_packet(timeout=None) == "ABCDEF"

    def test____recv_packet____ignore_other_socket_packets(
        self,
        client: UDPNetworkClient[str, str],
        udp_socket_factory: Callable[[], Socket],
    ) -> None:
        other_client = udp_socket_factory()
        other_client.sendto(b"ABCDEF", client.get_local_address())
        with pytest.raises(TimeoutError):
            client.recv_packet(timeout=0.1)

    def test____recv_packet____closed_client(self, client: UDPNetworkClient[str, str]) -> None:
        client.close()
        with pytest.raises(ClientClosedError):
            client.recv_packet()

    def test____recv_packet____invalid_data(self, client: UDPNetworkClient[str, str], server: Socket) -> None:
        server.sendto("\u00e9".encode("latin-1"), client.get_local_address())
        with pytest.raises(DatagramProtocolParseError):
            client.recv_packet()

    def test____iter_received_packets____yields_available_packets(
        self,
        client: UDPNetworkClient[str, str],
        server: Socket,
    ) -> None:
        for p in [b"A", b"B", b"C", b"D", b"E", b"F"]:
            server.sendto(p, client.get_local_address())

        # NOTE: Comparison using set because equality check does not verify order
        assert set(client.iter_received_packets(timeout=0.1)) == {"A", "B", "C", "D", "E", "F"}

    def test____fileno____consistency(self, client: UDPNetworkClient[str, str]) -> None:
        assert client.fileno() == client.socket.fileno()

    def test____fileno____closed_client(self, client: UDPNetworkClient[str, str]) -> None:
        client.close()
        assert client.fileno() == -1

    def test____get_local_address____consistency(self, socket_family: int, client: UDPNetworkClient[str, str]) -> None:
        address = client.get_local_address()
        if socket_family == AF_INET:
            assert isinstance(address, IPv4SocketAddress)
        else:
            assert isinstance(address, IPv6SocketAddress)
        assert address == client.socket.getsockname()

    def test____get_remote_address____consistency(self, socket_family: int, client: UDPNetworkClient[str, str]) -> None:
        address = client.get_remote_address()
        if socket_family == AF_INET:
            assert isinstance(address, IPv4SocketAddress)
        else:
            assert isinstance(address, IPv6SocketAddress)
        assert address == client.socket.getpeername()


class UDPServer(socketserver.UDPServer):
    class RequestHandler(socketserver.DatagramRequestHandler):
        def handle(self) -> None:
            data: bytes = self.rfile.read()
            self.wfile.write(data)

    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        socket_family: int,
    ) -> None:
        self.address_family = socket_family
        super().__init__(server_address, self.RequestHandler)


class TestUDPNetworkClientConnection:
    @pytest.fixture(autouse=True)
    @classmethod
    def server(cls, localhost_ip: str, socket_family: int) -> Iterator[socketserver.UDPServer]:
        from threading import Thread

        with UDPServer((localhost_ip, 0), socket_family) as server:
            server_thread = Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            yield server
            server.shutdown()
            server_thread.join()

    @pytest.fixture
    @staticmethod
    def remote_address(server: socketserver.UDPServer) -> tuple[str, int]:
        return server.server_address[:2]  # type: ignore[return-value]

    def test____dunder_init____connect_to_server(
        self,
        remote_address: tuple[str, int],
        datagram_protocol: DatagramProtocol[str, str],
    ) -> None:
        with UDPNetworkClient(remote_address, datagram_protocol) as client:
            assert client.get_local_address().host in {"127.0.0.1", "::1"}
            assert client.get_local_address().port > 0

            client.send_packet("Test")
            assert client.recv_packet() == "Test"

    def test____dunder_init____with_local_address(
        self,
        localhost_ip: str,
        remote_address: tuple[str, int],
        datagram_protocol: DatagramProtocol[str, str],
    ) -> None:
        with UDPNetworkClient(remote_address, datagram_protocol, local_address=(localhost_ip, 0)) as client:
            assert client.get_local_address().host == localhost_ip
            assert client.get_local_address().port > 0

            client.send_packet("Test")
            assert client.recv_packet() == "Test"

    def test____dunder_init____remote_address____not_set(
        self,
        udp_socket_factory: Callable[[], Socket],
        datagram_protocol: DatagramProtocol[str, str],
    ) -> None:
        with pytest.raises(OSError):
            _ = UDPNetworkClient(udp_socket_factory(), datagram_protocol)
