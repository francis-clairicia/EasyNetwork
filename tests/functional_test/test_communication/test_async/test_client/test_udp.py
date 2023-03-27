# -*- coding: Utf-8 -*-

from __future__ import annotations

import asyncio
from socket import AF_INET, socket as Socket
from typing import AsyncIterator, Callable

from easynetwork.async_api.client.udp import AsyncUDPNetworkClient, AsyncUDPNetworkEndpoint
from easynetwork.exceptions import ClientClosedError, DatagramProtocolParseError
from easynetwork.protocol import DatagramProtocol
from easynetwork.tools.socket import IPv4SocketAddress, IPv6SocketAddress, new_socket_address

import pytest
import pytest_asyncio

from .._utils import delay


@pytest.fixture
def udp_socket_factory(request: pytest.FixtureRequest, localhost: str) -> Callable[[], Socket]:
    udp_socket_factory: Callable[[], Socket] = request.getfixturevalue("udp_socket_factory")

    def bound_udp_socket_factory() -> Socket:
        sock = udp_socket_factory()
        sock.bind((localhost, 0))
        return sock

    return bound_udp_socket_factory


@pytest.mark.asyncio
class TestAsyncUDPNetworkClient:
    @pytest.fixture
    @staticmethod
    def server(udp_socket_factory: Callable[[], Socket]) -> Socket:
        return udp_socket_factory()

    @pytest_asyncio.fixture
    @staticmethod
    async def client(
        server: Socket,
        socket_family: int,
        localhost: str,
        datagram_protocol: DatagramProtocol[str, str],
    ) -> AsyncIterator[AsyncUDPNetworkClient[str, str]]:
        address: tuple[str, int] = server.getsockname()[:2]
        async with await AsyncUDPNetworkClient.create(
            address,
            datagram_protocol,
            family=socket_family,
            local_address=(localhost, 0),
        ) as client:
            yield client

    async def test____close____double_close(self, client: AsyncUDPNetworkClient[str, str]) -> None:
        assert not client.is_closing()
        await client.close()
        assert client.is_closing()
        await client.close()
        assert client.is_closing()

    async def test____send_packet____default(self, client: AsyncUDPNetworkClient[str, str], server: Socket) -> None:
        await client.send_packet("ABCDEF")
        assert server.recvfrom(1024) == (b"ABCDEF", client.get_local_address())

    @pytest.mark.platform_linux  # Windows and macOS do not raise error
    async def test____send_packet____connection_refused(self, client: AsyncUDPNetworkClient[str, str], server: Socket) -> None:
        server.close()
        with pytest.raises(ConnectionRefusedError):
            await client.send_packet("ABCDEF")

    @pytest.mark.platform_linux  # Windows and macOS do not raise error
    async def test____send_packet____connection_refused____after_previous_successful_try(
        self,
        client: AsyncUDPNetworkClient[str, str],
        server: Socket,
    ) -> None:
        await client.send_packet("ABC")
        assert server.recvfrom(1024) == (b"ABC", client.get_local_address())
        server.close()
        with pytest.raises(ConnectionRefusedError):
            await client.send_packet("DEF")

    async def test____send_packet____closed_client(self, client: AsyncUDPNetworkClient[str, str]) -> None:
        await client.close()
        with pytest.raises(ClientClosedError):
            await client.send_packet("ABCDEF")

    async def test____recv_packet____default(self, client: AsyncUDPNetworkClient[str, str], server: Socket) -> None:
        server.sendto(b"ABCDEF", client.get_local_address())
        assert await client.recv_packet() == "ABCDEF"

    async def test____recv_packet____ignore_other_socket_packets(
        self,
        client: AsyncUDPNetworkClient[str, str],
        udp_socket_factory: Callable[[], Socket],
    ) -> None:
        other_client = udp_socket_factory()
        other_client.sendto(b"ABCDEF", client.get_local_address())
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(client.recv_packet(), timeout=0.1)

    async def test____recv_packet____closed_client(self, client: AsyncUDPNetworkClient[str, str]) -> None:
        await client.close()
        with pytest.raises(ClientClosedError):
            await client.recv_packet()

    async def test____recv_packet____invalid_data(self, client: AsyncUDPNetworkClient[str, str], server: Socket) -> None:
        server.sendto("\u00E9".encode("latin-1"), client.get_local_address())
        with pytest.raises(DatagramProtocolParseError):
            await client.recv_packet()

    async def test____iter_received_packets____yields_available_packets_until_close(
        self,
        client: AsyncUDPNetworkClient[str, str],
        server: Socket,
    ) -> None:
        for p in [b"A", b"B", b"C", b"D", b"E", b"F"]:
            server.sendto(p, client.get_local_address())

        asyncio.create_task(delay(client.close, 0.5))

        # NOTE: Comparison using set because equality check does not verify order
        assert {p async for p in client.iter_received_packets()} == {"A", "B", "C", "D", "E", "F"}

    async def test____fileno____consistency(self, client: AsyncUDPNetworkClient[str, str]) -> None:
        assert client.fileno() == client.socket.fileno()

    async def test____fileno____closed_client(self, client: AsyncUDPNetworkClient[str, str]) -> None:
        await client.close()
        assert client.fileno() == -1

    async def test____get_local_address____consistency(self, socket_family: int, client: AsyncUDPNetworkClient[str, str]) -> None:
        address = client.get_local_address()
        if socket_family == AF_INET:
            assert isinstance(address, IPv4SocketAddress)
        else:
            assert isinstance(address, IPv6SocketAddress)
        assert address == client.socket.getsockname()

    async def test____get_remote_address____consistency(
        self, socket_family: int, client: AsyncUDPNetworkClient[str, str]
    ) -> None:
        address = client.get_remote_address()
        if socket_family == AF_INET:
            assert isinstance(address, IPv4SocketAddress)
        else:
            assert isinstance(address, IPv6SocketAddress)
        assert address == client.socket.getpeername()


@pytest.mark.asyncio
class TestUDPNetworkEndpoint:
    @pytest.fixture
    @staticmethod
    def server(udp_socket_factory: Callable[[], Socket]) -> Socket:
        return udp_socket_factory()

    @pytest_asyncio.fixture(params=["WITH_REMOTE", "WITHOUT_REMOTE"])
    @staticmethod
    async def client(
        request: pytest.FixtureRequest,
        socket_family: int,
        localhost: str,
        datagram_protocol: DatagramProtocol[str, str],
    ) -> AsyncIterator[AsyncUDPNetworkEndpoint[str, str]]:
        address: tuple[str, int] | None
        match getattr(request, "param"):
            case "WITH_REMOTE":
                server: Socket = request.getfixturevalue("server")
                address = server.getsockname()[:2]
            case "WITHOUT_REMOTE":
                address = None
            case invalid:
                pytest.fail(f"Invalid fixture param, got {invalid!r}")
        async with await AsyncUDPNetworkEndpoint.create(
            datagram_protocol,
            remote_address=address,
            family=socket_family,
            local_address=(localhost, 0),
        ) as client:
            yield client

    async def test____close____double_close(self, client: AsyncUDPNetworkEndpoint[str, str]) -> None:
        assert not client.is_closing()
        await client.close()
        assert client.is_closing()
        await client.close()
        assert client.is_closing()

    @pytest.mark.parametrize("client", ["WITHOUT_REMOTE"], indirect=True)
    async def test____send_packet_to____send_to_anyone(
        self,
        client: AsyncUDPNetworkEndpoint[str, str],
        udp_socket_factory: Callable[[], Socket],
    ) -> None:
        other_client_1 = udp_socket_factory()
        other_client_2 = udp_socket_factory()
        other_client_3 = udp_socket_factory()
        for other_client in [other_client_1, other_client_2, other_client_3]:
            await client.send_packet_to("ABCDEF", other_client.getsockname())
            assert other_client.recvfrom(1024) == (b"ABCDEF", client.get_local_address())

    @pytest.mark.parametrize("client", ["WITHOUT_REMOTE"], indirect=True)
    async def test____send_packet_to____None_is_invalid(self, client: AsyncUDPNetworkEndpoint[str, str]) -> None:
        with pytest.raises(ValueError):
            await client.send_packet_to("ABCDEF", None)

    @pytest.mark.parametrize("client", ["WITH_REMOTE"], indirect=True)
    async def test____send_packet_to____send_to_connected_address____via_None(
        self,
        client: AsyncUDPNetworkEndpoint[str, str],
        server: Socket,
    ) -> None:
        await client.send_packet_to("ABCDEF", None)
        assert server.recvfrom(1024) == (b"ABCDEF", client.get_local_address())

    @pytest.mark.parametrize("client", ["WITH_REMOTE"], indirect=True)
    async def test____send_packet_to____send_to_connected_address____explicit(
        self,
        client: AsyncUDPNetworkEndpoint[str, str],
        server: Socket,
    ) -> None:
        await client.send_packet_to("ABCDEF", server.getsockname())
        assert server.recvfrom(1024) == (b"ABCDEF", client.get_local_address())

    async def test____send_packet_to____invalid_address(
        self,
        client: AsyncUDPNetworkEndpoint[str, str],
        udp_socket_factory: Callable[[], Socket],
    ) -> None:
        other_client = udp_socket_factory()
        other_client_address = other_client.getsockname()

        if client.get_remote_address() is None:
            # Even if other socket is closed, there should be no error

            other_client.close()

            await client.send_packet_to("ABCDEF", other_client_address)
        else:
            # The given address is not the configured remote address
            with pytest.raises(ValueError):
                await client.send_packet_to("ABCDEF", other_client_address)

    @pytest.mark.platform_linux  # Windows and macOS do not raise error
    @pytest.mark.parametrize("client", ["WITH_REMOTE"], indirect=True)
    async def test____send_packet_to____connection_refused(
        self,
        client: AsyncUDPNetworkEndpoint[str, str],
        server: Socket,
    ) -> None:
        address = server.getsockname()
        server.close()
        with pytest.raises(ConnectionRefusedError):
            await client.send_packet_to("ABCDEF", address)

    @pytest.mark.platform_linux  # Windows and macOS do not raise error
    @pytest.mark.parametrize("client", ["WITH_REMOTE"], indirect=True)
    async def test____send_packet____connection_refused____after_previous_successful_try(
        self,
        client: AsyncUDPNetworkEndpoint[str, str],
        server: Socket,
    ) -> None:
        address = server.getsockname()
        await client.send_packet_to("ABC", address)
        assert server.recvfrom(1024) == (b"ABC", client.get_local_address())
        server.close()
        with pytest.raises(ConnectionRefusedError):
            await client.send_packet_to("DEF", address)

    async def test____send_packet_to____closed_client(self, client: AsyncUDPNetworkEndpoint[str, str], server: Socket) -> None:
        address = server.getsockname()
        await client.close()
        with pytest.raises(ClientClosedError):
            await client.send_packet_to("ABCDEF", address)

    @pytest.mark.parametrize("client", ["WITHOUT_REMOTE"], indirect=True)
    async def test____recv_packet_from____receive_from_anyone(
        self,
        client: AsyncUDPNetworkEndpoint[str, str],
        socket_family: int,
        udp_socket_factory: Callable[[], Socket],
    ) -> None:
        other_client_1 = udp_socket_factory()
        other_client_2 = udp_socket_factory()
        other_client_3 = udp_socket_factory()
        for other_client in [other_client_1, other_client_2, other_client_3]:
            other_client.sendto(b"ABCDEF", client.get_local_address())
            packet, sender = await client.recv_packet_from()
            assert packet == "ABCDEF"
            if socket_family == AF_INET:
                assert isinstance(sender, IPv4SocketAddress)
            else:
                assert isinstance(sender, IPv6SocketAddress)
            assert sender == new_socket_address(other_client.getsockname(), socket_family)

    @pytest.mark.parametrize("client", ["WITH_REMOTE"], indirect=True)
    async def test____recv_packet_from____receive_from_remote(
        self,
        client: AsyncUDPNetworkEndpoint[str, str],
        server: Socket,
        socket_family: int,
    ) -> None:
        server.sendto(b"ABCDEF", client.get_local_address())
        packet, sender = await client.recv_packet_from()
        assert packet == "ABCDEF"
        if socket_family == AF_INET:
            assert isinstance(sender, IPv4SocketAddress)
        else:
            assert isinstance(sender, IPv6SocketAddress)
        assert sender == new_socket_address(server.getsockname(), socket_family)

    @pytest.mark.parametrize("client", ["WITH_REMOTE"], indirect=True)
    async def test____recv_packet_from____ignore_other_socket_packets(
        self,
        client: AsyncUDPNetworkEndpoint[str, str],
        udp_socket_factory: Callable[[], Socket],
    ) -> None:
        other_client = udp_socket_factory()
        other_client.sendto(b"ABCDEF", client.get_local_address())
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(client.recv_packet_from(), timeout=0.1)

    async def test____recv_packet_from____closed_client(self, client: AsyncUDPNetworkEndpoint[str, str]) -> None:
        await client.close()
        with pytest.raises(ClientClosedError):
            await client.recv_packet_from()

    async def test____recv_packet_from____invalid_data(self, client: AsyncUDPNetworkEndpoint[str, str], server: Socket) -> None:
        server.sendto("\u00E9".encode("latin-1"), client.get_local_address())
        with pytest.raises(DatagramProtocolParseError):
            await client.recv_packet_from()

    async def test____iter_received_packets_from____yields_available_packets(
        self,
        client: AsyncUDPNetworkEndpoint[str, str],
        socket_family: int,
        server: Socket,
    ) -> None:
        server_address = new_socket_address(server.getsockname(), socket_family)
        for p in [b"A", b"B", b"C", b"D", b"E", b"F"]:
            server.sendto(p, client.get_local_address())

        asyncio.create_task(delay(client.close, 0.5))

        # NOTE: Comparison using set because equality check does not verify order
        assert {(p, addr) async for p, addr in client.iter_received_packets_from()} == {
            ("A", server_address),
            ("B", server_address),
            ("C", server_address),
            ("D", server_address),
            ("E", server_address),
            ("F", server_address),
        }

    async def test____fileno____consistency(self, client: AsyncUDPNetworkEndpoint[str, str]) -> None:
        assert client.fileno() == client.socket.fileno()

    async def test____fileno____closed_client(self, client: AsyncUDPNetworkEndpoint[str, str]) -> None:
        await client.close()
        assert client.fileno() == -1

    async def test____get_local_address____consistency(
        self,
        socket_family: int,
        client: AsyncUDPNetworkEndpoint[str, str],
    ) -> None:
        address = client.get_local_address()
        if socket_family == AF_INET:
            assert isinstance(address, IPv4SocketAddress)
        else:
            assert isinstance(address, IPv6SocketAddress)
        assert address == client.socket.getsockname()

    @pytest.mark.parametrize("client", ["WITH_REMOTE"], indirect=True)
    async def test____get_remote_address____consistency(
        self,
        socket_family: int,
        client: AsyncUDPNetworkEndpoint[str, str],
    ) -> None:
        address = client.get_remote_address()
        if socket_family == AF_INET:
            assert isinstance(address, IPv4SocketAddress)
        else:
            assert isinstance(address, IPv6SocketAddress)
        assert address == client.socket.getpeername()
