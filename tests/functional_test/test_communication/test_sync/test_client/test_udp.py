# -*- coding: utf-8 -*-

from __future__ import annotations

from socket import AF_INET, socket as Socket
from typing import Any, Callable, Iterator

from easynetwork.api_sync.client.udp import UDPNetworkClient, UDPNetworkEndpoint
from easynetwork.exceptions import ClientClosedError, DatagramProtocolParseError
from easynetwork.protocol import DatagramProtocol
from easynetwork.tools.socket import IPv4SocketAddress, IPv6SocketAddress, new_socket_address

import pytest


@pytest.fixture
def udp_socket_factory(request: pytest.FixtureRequest, localhost_ip: str) -> Callable[[], Socket]:
    udp_socket_factory: Callable[[], Socket] = request.getfixturevalue("udp_socket_factory")

    def bound_udp_socket_factory() -> Socket:
        sock = udp_socket_factory()
        sock.bind((localhost_ip, 0))
        return sock

    return bound_udp_socket_factory


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

    @pytest.mark.platform_linux  # Windows and MacOS do not raise error
    def test____send_packet____connection_refused(self, client: UDPNetworkClient[str, str], server: Socket) -> None:
        server.close()
        with pytest.raises(ConnectionRefusedError):
            client.send_packet("ABCDEF")

    @pytest.mark.platform_linux  # Windows and MacOS do not raise error
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


class TestUDPNetworkEndpoint:
    @pytest.fixture
    @staticmethod
    def server(udp_socket_factory: Callable[[], Socket]) -> Socket:
        return udp_socket_factory()

    @pytest.fixture(params=["WITH_REMOTE", "WITHOUT_REMOTE"])
    @staticmethod
    def client(
        request: pytest.FixtureRequest,
        localhost_ip: str,
        datagram_protocol: DatagramProtocol[str, str],
    ) -> Iterator[UDPNetworkEndpoint[str, str]]:
        address: tuple[str, int] | None
        match getattr(request, "param"):
            case "WITH_REMOTE":
                server: Socket = request.getfixturevalue("server")
                address = server.getsockname()[:2]
            case "WITHOUT_REMOTE":
                address = None
            case invalid:
                pytest.fail(f"Invalid fixture param, got {invalid!r}")
        with UDPNetworkEndpoint(
            datagram_protocol,
            remote_address=address,
            local_address=(localhost_ip, 0),
        ) as client:
            yield client

    def test____close____idempotent(self, client: UDPNetworkEndpoint[str, str]) -> None:
        assert not client.is_closed()
        client.close()
        assert client.is_closed()
        client.close()
        assert client.is_closed()

    @pytest.mark.parametrize("client", ["WITHOUT_REMOTE"], indirect=True)
    def test____send_packet_to____send_to_anyone(
        self,
        client: UDPNetworkEndpoint[str, str],
        udp_socket_factory: Callable[[], Socket],
    ) -> None:
        other_client_1 = udp_socket_factory()
        other_client_2 = udp_socket_factory()
        other_client_3 = udp_socket_factory()
        for other_client in [other_client_1, other_client_2, other_client_3]:
            client.send_packet_to("ABCDEF", other_client.getsockname())
            assert other_client.recvfrom(1024) == (b"ABCDEF", client.get_local_address())

    @pytest.mark.parametrize("client", ["WITHOUT_REMOTE"], indirect=True)
    def test____send_packet_to____None_is_invalid(self, client: UDPNetworkEndpoint[str, str]) -> None:
        with pytest.raises(ValueError):
            client.send_packet_to("ABCDEF", None)

    @pytest.mark.parametrize("client", ["WITH_REMOTE"], indirect=True)
    def test____send_packet_to____send_to_connected_address____via_None(
        self,
        client: UDPNetworkEndpoint[str, str],
        server: Socket,
    ) -> None:
        client.send_packet_to("ABCDEF", None)
        assert server.recvfrom(1024) == (b"ABCDEF", client.get_local_address())

    @pytest.mark.parametrize("client", ["WITH_REMOTE"], indirect=True)
    def test____send_packet_to____send_to_connected_address____explicit(
        self,
        client: UDPNetworkEndpoint[str, str],
        server: Socket,
    ) -> None:
        client.send_packet_to("ABCDEF", server.getsockname())
        assert server.recvfrom(1024) == (b"ABCDEF", client.get_local_address())

    def test____send_packet_to____invalid_address(
        self,
        client: UDPNetworkEndpoint[str, str],
        udp_socket_factory: Callable[[], Socket],
    ) -> None:
        other_client = udp_socket_factory()
        other_client_address = other_client.getsockname()

        if client.get_remote_address() is None:
            # Even if other socket is closed, there should be no error

            other_client.close()

            client.send_packet_to("ABCDEF", other_client_address)
        else:
            # The given address is not the configured remote address
            with pytest.raises(ValueError):
                client.send_packet_to("ABCDEF", other_client_address)

    @pytest.mark.platform_linux  # Windows and MacOS do not raise error
    @pytest.mark.parametrize("client", ["WITH_REMOTE"], indirect=True)
    def test____send_packet_to____connection_refused(self, client: UDPNetworkEndpoint[str, str], server: Socket) -> None:
        address = server.getsockname()
        server.close()
        with pytest.raises(ConnectionRefusedError):
            client.send_packet_to("ABCDEF", address)

    @pytest.mark.platform_linux  # Windows and MacOS do not raise error
    @pytest.mark.parametrize("client", ["WITH_REMOTE"], indirect=True)
    def test____send_packet____connection_refused____after_previous_successful_try(
        self,
        client: UDPNetworkEndpoint[str, str],
        server: Socket,
    ) -> None:
        address = server.getsockname()
        client.send_packet_to("ABC", address)
        assert server.recvfrom(1024) == (b"ABC", client.get_local_address())
        server.close()
        with pytest.raises(ConnectionRefusedError):
            client.send_packet_to("DEF", address)

    def test____send_packet_to____closed_client(self, client: UDPNetworkEndpoint[str, str], server: Socket) -> None:
        address = server.getsockname()
        client.close()
        with pytest.raises(ClientClosedError):
            client.send_packet_to("ABCDEF", address)

    @pytest.mark.parametrize("client", ["WITHOUT_REMOTE"], indirect=True)
    def test____recv_packet_from____receive_from_anyone(
        self,
        client: UDPNetworkEndpoint[str, str],
        socket_family: int,
        udp_socket_factory: Callable[[], Socket],
    ) -> None:
        other_client_1 = udp_socket_factory()
        other_client_2 = udp_socket_factory()
        other_client_3 = udp_socket_factory()
        for other_client in [other_client_1, other_client_2, other_client_3]:
            other_client.sendto(b"ABCDEF", client.get_local_address())
            packet, sender = client.recv_packet_from()
            assert packet == "ABCDEF"
            if socket_family == AF_INET:
                assert isinstance(sender, IPv4SocketAddress)
            else:
                assert isinstance(sender, IPv6SocketAddress)
            assert sender == new_socket_address(other_client.getsockname(), socket_family)

    @pytest.mark.parametrize("client", ["WITH_REMOTE"], indirect=True)
    def test____recv_packet_from____receive_from_remote(
        self,
        client: UDPNetworkEndpoint[str, str],
        server: Socket,
        socket_family: int,
    ) -> None:
        server.sendto(b"ABCDEF", client.get_local_address())
        packet, sender = client.recv_packet_from()
        assert packet == "ABCDEF"
        if socket_family == AF_INET:
            assert isinstance(sender, IPv4SocketAddress)
        else:
            assert isinstance(sender, IPv6SocketAddress)
        assert sender == new_socket_address(server.getsockname(), socket_family)

    def test____recv_packet_from____timeout(
        self,
        client: UDPNetworkEndpoint[str, str],
        socket_family: int,
        server: Socket,
        schedule_call_in_thread: Callable[[float, Callable[[], Any]], None],
    ) -> None:
        schedule_call_in_thread(0.1, lambda: server.sendto(b"ABCDEF", client.get_local_address()))
        with pytest.raises(TimeoutError):
            client.recv_packet_from(timeout=0)
        assert client.recv_packet_from(timeout=None) == ("ABCDEF", new_socket_address(server.getsockname(), socket_family))

    @pytest.mark.parametrize("client", ["WITH_REMOTE"], indirect=True)
    def test____recv_packet_from____ignore_other_socket_packets(
        self,
        client: UDPNetworkEndpoint[str, str],
        udp_socket_factory: Callable[[], Socket],
    ) -> None:
        other_client = udp_socket_factory()
        other_client.sendto(b"ABCDEF", client.get_local_address())
        with pytest.raises(TimeoutError):
            client.recv_packet_from(timeout=0.1)

    def test____recv_packet_from____closed_client(self, client: UDPNetworkEndpoint[str, str]) -> None:
        client.close()
        with pytest.raises(ClientClosedError):
            client.recv_packet_from()

    def test____recv_packet_from____invalid_data(self, client: UDPNetworkEndpoint[str, str], server: Socket) -> None:
        server.sendto("\u00E9".encode("latin-1"), client.get_local_address())
        with pytest.raises(DatagramProtocolParseError):
            client.recv_packet_from()

    def test____iter_received_packets_from____yields_available_packets(
        self,
        client: UDPNetworkEndpoint[str, str],
        socket_family: int,
        server: Socket,
    ) -> None:
        server_address = new_socket_address(server.getsockname(), socket_family)
        for p in [b"A", b"B", b"C", b"D", b"E", b"F"]:
            server.sendto(p, client.get_local_address())

        # NOTE: Comparison using set because equality check does not verify order
        assert set(client.iter_received_packets_from(timeout=0.1)) == {
            ("A", server_address),
            ("B", server_address),
            ("C", server_address),
            ("D", server_address),
            ("E", server_address),
            ("F", server_address),
        }

    def test____fileno____consistency(self, client: UDPNetworkEndpoint[str, str]) -> None:
        assert client.fileno() == client.socket.fileno()

    def test____fileno____closed_client(self, client: UDPNetworkEndpoint[str, str]) -> None:
        client.close()
        assert client.fileno() == -1

    def test____get_local_address____consistency(self, socket_family: int, client: UDPNetworkEndpoint[str, str]) -> None:
        address = client.get_local_address()
        if socket_family == AF_INET:
            assert isinstance(address, IPv4SocketAddress)
        else:
            assert isinstance(address, IPv6SocketAddress)
        assert address == client.socket.getsockname()

    @pytest.mark.parametrize("client", ["WITH_REMOTE"], indirect=True)
    def test____get_remote_address____consistency(self, socket_family: int, client: UDPNetworkEndpoint[str, str]) -> None:
        address = client.get_remote_address()
        if socket_family == AF_INET:
            assert isinstance(address, IPv4SocketAddress)
        else:
            assert isinstance(address, IPv6SocketAddress)
        assert address == client.socket.getpeername()
