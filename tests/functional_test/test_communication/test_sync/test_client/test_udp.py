from __future__ import annotations

from collections.abc import Callable, Iterator
from socket import AF_INET, socket as Socket
from typing import Any

from easynetwork.api_sync.client.udp import UDPNetworkClient
from easynetwork.exceptions import ClientClosedError, DatagramProtocolParseError
from easynetwork.lowlevel.socket import IPv4SocketAddress, IPv6SocketAddress
from easynetwork.protocol import DatagramProtocol

import pytest

from .....tools import PlatformMarkers


@pytest.fixture
def udp_socket_factory(request: pytest.FixtureRequest, localhost_ip: str) -> Callable[[], Socket]:
    udp_socket_factory: Callable[[], Socket] = request.getfixturevalue("udp_socket_factory")

    def bound_udp_socket_factory() -> Socket:
        sock = udp_socket_factory()
        sock.bind((localhost_ip, 0))
        return sock

    return bound_udp_socket_factory


@pytest.mark.flaky(retries=3, delay=1)
class TestUDPNetworkClient:
    @pytest.fixture
    @staticmethod
    def server(udp_socket_factory: Callable[[], Socket]) -> Socket:
        return udp_socket_factory()

    @pytest.fixture
    @staticmethod
    def client(
        server: Socket,
        localhost_ip: str,
        datagram_protocol: DatagramProtocol[str, str],
    ) -> Iterator[UDPNetworkClient[str, str]]:
        address: tuple[str, int] = server.getsockname()[:2]
        with UDPNetworkClient(address, datagram_protocol, local_address=(localhost_ip, 0)) as client:
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

    # Windows and MacOS do not raise error
    @PlatformMarkers.skipif_platform_win32
    @PlatformMarkers.skipif_platform_macOS
    def test____send_packet____connection_refused(self, client: UDPNetworkClient[str, str], server: Socket) -> None:
        server.close()
        with pytest.raises(ConnectionRefusedError):
            client.send_packet("ABCDEF")

    # Windows and MacOS do not raise error
    @PlatformMarkers.skipif_platform_win32
    @PlatformMarkers.skipif_platform_macOS
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
        server.sendto("\u00E9".encode("latin-1"), client.get_local_address())
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
