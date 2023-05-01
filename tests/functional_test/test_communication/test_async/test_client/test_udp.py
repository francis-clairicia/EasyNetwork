# -*- coding: Utf-8 -*-

from __future__ import annotations

import asyncio
import contextlib
from socket import AF_INET, socket as Socket
from typing import Any, AsyncIterator, Callable

from easynetwork.api_async.client.udp import AsyncUDPNetworkClient, AsyncUDPNetworkEndpoint
from easynetwork.exceptions import ClientClosedError, DatagramProtocolParseError
from easynetwork.protocol import DatagramProtocol
from easynetwork.tools.socket import IPv4SocketAddress, IPv6SocketAddress, SocketProxy, new_socket_address

import pytest
import pytest_asyncio

from .._utils import delay
from ..conftest import use_asyncio_transport_xfail_uvloop


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

    @pytest.fixture
    @staticmethod
    def remote_address(server: Socket) -> tuple[str, int]:
        return server.getsockname()[:2]

    @pytest.fixture(params=[False, True], ids=lambda boolean: f"use_external_socket=={boolean}")
    @staticmethod
    def use_external_socket(request: pytest.FixtureRequest) -> Socket | None:
        use_external_socket: bool = getattr(request, "param")
        if use_external_socket:
            udp_socket_factory: Callable[[], Socket] = request.getfixturevalue("udp_socket_factory")
            return udp_socket_factory()
        return None

    @pytest_asyncio.fixture
    @staticmethod
    async def client(
        remote_address: tuple[str, int],
        use_external_socket: Socket | None,
        socket_family: int,
        datagram_protocol: DatagramProtocol[str, str],
        use_asyncio_transport: bool,
    ) -> AsyncIterator[AsyncUDPNetworkClient[str, str]]:
        if use_external_socket is not None:
            use_external_socket.connect(remote_address)
            client = AsyncUDPNetworkClient(
                use_external_socket, datagram_protocol, backend_kwargs={"transport": use_asyncio_transport}
            )
        else:
            client = AsyncUDPNetworkClient(
                remote_address, datagram_protocol, family=socket_family, backend_kwargs={"transport": use_asyncio_transport}
            )
        async with client:
            assert client.is_connected()
            yield client

    @pytest.mark.parametrize("ipaddr_any", ["", None], ids=repr)
    async def test____dunder_init____local_address____bind_to_all_interfaces(
        self,
        remote_address: tuple[str, int],
        ipaddr_any: str,
        socket_family: int,
        datagram_protocol: DatagramProtocol[str, str],
    ) -> None:
        async with AsyncUDPNetworkClient(
            remote_address,
            datagram_protocol,
            family=socket_family,
            local_address=(ipaddr_any, 0),
        ) as client:
            assert client.is_connected()
            assert client.get_local_address().port > 0

    async def test____dunder_init____remote_address____not_set(
        self,
        udp_socket_factory: Callable[[], Socket],
        datagram_protocol: DatagramProtocol[str, str],
    ) -> None:
        with pytest.raises(OSError, match=r"^No remote address configured$"):
            _ = AsyncUDPNetworkClient(udp_socket_factory(), datagram_protocol)

    async def test____aclose____idempotent(self, client: AsyncUDPNetworkClient[str, str]) -> None:
        assert not client.is_closing()
        await client.aclose()
        assert client.is_closing()
        await client.aclose()
        assert client.is_closing()

    async def test____send_packet____default(self, client: AsyncUDPNetworkClient[str, str], server: Socket) -> None:
        await client.send_packet("ABCDEF")
        assert await asyncio.to_thread(server.recvfrom, 1024) == (b"ABCDEF", client.get_local_address())

    # @use_asyncio_transport_xfail_uvloop
    @pytest.mark.platform_linux  # Windows and MacOS do not raise error
    async def test____send_packet____connection_refused(self, client: AsyncUDPNetworkClient[str, str], server: Socket) -> None:
        server.close()
        with pytest.raises(ConnectionRefusedError):
            await client.send_packet("ABCDEF")

    # @use_asyncio_transport_xfail_uvloop
    @pytest.mark.platform_linux  # Windows and MacOS do not raise error
    async def test____send_packet____connection_refused____after_previous_successful_try(
        self,
        client: AsyncUDPNetworkClient[str, str],
        server: Socket,
    ) -> None:
        await client.send_packet("ABC")
        assert await asyncio.to_thread(server.recvfrom, 1024) == (b"ABC", client.get_local_address())
        server.close()
        with pytest.raises(ConnectionRefusedError):
            await client.send_packet("DEF")

    async def test____send_packet____closed_client(self, client: AsyncUDPNetworkClient[str, str]) -> None:
        await client.aclose()
        with pytest.raises(ClientClosedError):
            await client.send_packet("ABCDEF")

    @use_asyncio_transport_xfail_uvloop
    async def test____recv_packet____default(self, client: AsyncUDPNetworkClient[str, str], server: Socket) -> None:
        server.sendto(b"ABCDEF", client.get_local_address())
        assert await client.recv_packet() == "ABCDEF"

    @use_asyncio_transport_xfail_uvloop
    async def test____recv_packet____ignore_other_socket_packets(
        self,
        client: AsyncUDPNetworkClient[str, str],
        udp_socket_factory: Callable[[], Socket],
    ) -> None:
        other_client = udp_socket_factory()
        other_client.sendto(b"ABCDEF", client.get_local_address())
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(client.recv_packet(), timeout=0.1)

    async def test____recv_packet____closed_client(self, client: AsyncUDPNetworkClient[str, str]) -> None:
        await client.aclose()
        with pytest.raises(ClientClosedError):
            await client.recv_packet()

    @use_asyncio_transport_xfail_uvloop
    async def test____recv_packet____invalid_data(self, client: AsyncUDPNetworkClient[str, str], server: Socket) -> None:
        server.sendto("\u00E9".encode("latin-1"), client.get_local_address())
        with pytest.raises(DatagramProtocolParseError):
            await client.recv_packet()

    @use_asyncio_transport_xfail_uvloop
    async def test____iter_received_packets____yields_available_packets_until_close(
        self,
        client: AsyncUDPNetworkClient[str, str],
        server: Socket,
    ) -> None:
        for p in [b"A", b"B", b"C", b"D", b"E", b"F"]:
            server.sendto(p, client.get_local_address())

        close_task = asyncio.create_task(delay(client.aclose, 0.5))
        try:
            # NOTE: Comparison using set because equality check does not verify order
            assert {p async for p in client.iter_received_packets()} == {"A", "B", "C", "D", "E", "F"}
        finally:
            close_task.cancel()

    async def test____fileno____consistency(self, client: AsyncUDPNetworkClient[str, str]) -> None:
        assert client.fileno() == client.socket.fileno()

    async def test____fileno____closed_client(self, client: AsyncUDPNetworkClient[str, str]) -> None:
        await client.aclose()
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
class TestAsyncUDPNetworkClientConnection:
    class EchoProtocol(asyncio.DatagramProtocol):
        transport: asyncio.DatagramTransport | None = None

        def connection_made(self, transport: asyncio.DatagramTransport) -> None:  # type: ignore[override]
            self.transport = transport

        def connection_lost(self, exc: Exception | None) -> None:
            self.transport = None

        def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
            if self.transport is not None:
                self.transport.sendto(data, addr)

    @pytest_asyncio.fixture
    @classmethod
    async def server(
        cls,
        event_loop: asyncio.AbstractEventLoop,
        localhost: str,
        socket_family: int,
    ) -> AsyncIterator[asyncio.DatagramTransport]:
        transport, _ = await event_loop.create_datagram_endpoint(
            cls.EchoProtocol,
            local_addr=(localhost, 0),
            family=socket_family,
        )
        try:
            yield transport
        finally:
            transport.close()

    @pytest.fixture
    @staticmethod
    def remote_address(server: asyncio.DatagramTransport) -> tuple[str, int]:
        return server.get_extra_info("sockname")[:2]

    @pytest.fixture
    @staticmethod
    def backend_kwargs(use_asyncio_transport: bool) -> dict[str, Any]:
        return {"transport": use_asyncio_transport}

    async def test____wait_connected____idempotent(
        self,
        remote_address: tuple[str, int],
        datagram_protocol: DatagramProtocol[str, str],
        socket_family: int,
        backend_kwargs: dict[str, Any],
    ) -> None:
        async with AsyncUDPNetworkClient(
            remote_address,
            datagram_protocol,
            family=socket_family,
            backend_kwargs=backend_kwargs,
        ) as client:
            await client.wait_connected()
            assert client.is_connected()
            await client.wait_connected()
            assert client.is_connected()

    async def test____wait_connected____simultaneous(
        self,
        remote_address: tuple[str, int],
        datagram_protocol: DatagramProtocol[str, str],
        socket_family: int,
        backend_kwargs: dict[str, Any],
    ) -> None:
        async with AsyncUDPNetworkClient(
            remote_address,
            datagram_protocol,
            family=socket_family,
            backend_kwargs=backend_kwargs,
        ) as client:
            async with asyncio.TaskGroup() as task_group:
                task_group.create_task(client.wait_connected())
                task_group.create_task(client.wait_connected())
                await asyncio.sleep(0)
            assert client.is_connected()

    async def test____wait_connected____is_closing____connection_not_performed_yet(
        self,
        remote_address: tuple[str, int],
        datagram_protocol: DatagramProtocol[str, str],
        socket_family: int,
        backend_kwargs: dict[str, Any],
    ) -> None:
        async with contextlib.aclosing(
            AsyncUDPNetworkClient(
                remote_address,
                datagram_protocol,
                family=socket_family,
                backend_kwargs=backend_kwargs,
            )
        ) as client:
            assert not client.is_connected()
            assert not client.is_closing()
            await client.wait_connected()
            assert client.is_connected()
            assert not client.is_closing()

    async def test____wait_connected____close_before_trying_to_connect(
        self,
        remote_address: tuple[str, int],
        datagram_protocol: DatagramProtocol[str, str],
        socket_family: int,
        backend_kwargs: dict[str, Any],
    ) -> None:
        async with contextlib.aclosing(
            AsyncUDPNetworkClient(
                remote_address,
                datagram_protocol,
                family=socket_family,
                backend_kwargs=backend_kwargs,
            )
        ) as client:
            await client.aclose()
            with pytest.raises(ClientClosedError):
                await client.wait_connected()

    async def test____socket_property____connection_not_performed_yet(
        self,
        remote_address: tuple[str, int],
        datagram_protocol: DatagramProtocol[str, str],
        socket_family: int,
        backend_kwargs: dict[str, Any],
    ) -> None:
        async with contextlib.aclosing(
            AsyncUDPNetworkClient(
                remote_address,
                datagram_protocol,
                family=socket_family,
                backend_kwargs=backend_kwargs,
            )
        ) as client:
            with pytest.raises(OSError):
                _ = client.socket

            await client.wait_connected()

            assert isinstance(client.socket, SocketProxy)

    async def test____get_local_address____connection_not_performed_yet(
        self,
        remote_address: tuple[str, int],
        datagram_protocol: DatagramProtocol[str, str],
        socket_family: int,
        backend_kwargs: dict[str, Any],
    ) -> None:
        async with contextlib.aclosing(
            AsyncUDPNetworkClient(
                remote_address,
                datagram_protocol,
                family=socket_family,
                backend_kwargs=backend_kwargs,
            )
        ) as client:
            with pytest.raises(OSError):
                _ = client.get_local_address()

            await client.wait_connected()

            assert client.get_local_address()

    async def test____get_remote_address____connection_not_performed_yet(
        self,
        remote_address: tuple[str, int],
        datagram_protocol: DatagramProtocol[str, str],
        socket_family: int,
        backend_kwargs: dict[str, Any],
    ) -> None:
        async with contextlib.aclosing(
            AsyncUDPNetworkClient(
                remote_address,
                datagram_protocol,
                family=socket_family,
                backend_kwargs=backend_kwargs,
            )
        ) as client:
            with pytest.raises(OSError):
                _ = client.get_remote_address()

            await client.wait_connected()

            assert client.get_remote_address()[:2] == remote_address

    async def test____fileno____connection_not_performed_yet(
        self,
        remote_address: tuple[str, int],
        datagram_protocol: DatagramProtocol[str, str],
        socket_family: int,
        backend_kwargs: dict[str, Any],
    ) -> None:
        async with contextlib.aclosing(
            AsyncUDPNetworkClient(
                remote_address,
                datagram_protocol,
                family=socket_family,
                backend_kwargs=backend_kwargs,
            )
        ) as client:
            assert client.fileno() == -1

            await client.wait_connected()

            assert client.fileno() > -1

    @use_asyncio_transport_xfail_uvloop
    async def test____send_packet____recv_packet____implicit_connection(
        self,
        remote_address: tuple[str, int],
        datagram_protocol: DatagramProtocol[str, str],
        socket_family: int,
        backend_kwargs: dict[str, Any],
    ) -> None:
        async with contextlib.aclosing(
            AsyncUDPNetworkClient(
                remote_address,
                datagram_protocol,
                family=socket_family,
                backend_kwargs=backend_kwargs,
            )
        ) as client:
            assert not client.is_connected()

            await client.send_packet("Connected")
            assert await client.recv_packet() == "Connected"

            assert client.is_connected()


@pytest.mark.asyncio
class TestAsyncUDPNetworkEndpoint:
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
        use_asyncio_transport: bool,
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
        async with AsyncUDPNetworkEndpoint(
            datagram_protocol,
            remote_address=address,
            family=socket_family,
            local_address=(localhost, 0),
            backend_kwargs={"transport": use_asyncio_transport},
        ) as client:
            assert client.is_bound()
            yield client

    async def test____dunder_init____unbound_socket(
        self,
        socket_family: int,
        datagram_protocol: DatagramProtocol[str, str],
    ) -> None:
        from socket import SOCK_DGRAM

        socket = Socket(socket_family, SOCK_DGRAM)
        async with AsyncUDPNetworkEndpoint(socket=socket, protocol=datagram_protocol) as client:
            assert client.is_bound()
            assert client.get_local_address().port > 0

    @pytest.mark.parametrize("ipaddr_any", ["", None], ids=repr)
    async def test____dunder_init____local_address____bind_to_all_interfaces(
        self,
        ipaddr_any: str,
        socket_family: int,
        datagram_protocol: DatagramProtocol[str, str],
    ) -> None:
        async with AsyncUDPNetworkEndpoint(datagram_protocol, family=socket_family, local_address=(ipaddr_any, 0)) as client:
            assert client.is_bound()
            assert client.get_local_address().port > 0

    async def test____aclose____idempotent(self, client: AsyncUDPNetworkEndpoint[str, str]) -> None:
        assert not client.is_closing()
        await client.aclose()
        assert client.is_closing()
        await client.aclose()
        assert client.is_closing()

    @use_asyncio_transport_xfail_uvloop
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
            assert await asyncio.to_thread(other_client.recvfrom, 1024) == (b"ABCDEF", client.get_local_address())

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
        assert await asyncio.to_thread(server.recvfrom, 1024) == (b"ABCDEF", client.get_local_address())

    @pytest.mark.parametrize("client", ["WITH_REMOTE"], indirect=True)
    async def test____send_packet_to____send_to_connected_address____explicit(
        self,
        client: AsyncUDPNetworkEndpoint[str, str],
        server: Socket,
    ) -> None:
        await client.send_packet_to("ABCDEF", server.getsockname())
        assert await asyncio.to_thread(server.recvfrom, 1024) == (b"ABCDEF", client.get_local_address())

    @pytest.mark.parametrize(
        ["client", "use_asyncio_transport"],
        [
            pytest.param("WITH_REMOTE", False),
            pytest.param("WITH_REMOTE", True),
            pytest.param("WITHOUT_REMOTE", False, marks=pytest.mark.xfail_uvloop),
            pytest.param("WITHOUT_REMOTE", True),
        ],
        indirect=True,
    )
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

    @pytest.mark.platform_linux  # Windows and MacOS do not raise error
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

    @pytest.mark.platform_linux  # Windows and MacOS do not raise error
    @pytest.mark.parametrize("client", ["WITH_REMOTE"], indirect=True)
    async def test____send_packet____connection_refused____after_previous_successful_try(
        self,
        client: AsyncUDPNetworkEndpoint[str, str],
        server: Socket,
    ) -> None:
        address = server.getsockname()
        await client.send_packet_to("ABC", address)
        assert await asyncio.to_thread(server.recvfrom, 1024) == (b"ABC", client.get_local_address())
        server.close()
        with pytest.raises(ConnectionRefusedError):
            await client.send_packet_to("DEF", address)

    async def test____send_packet_to____closed_client(self, client: AsyncUDPNetworkEndpoint[str, str], server: Socket) -> None:
        address = server.getsockname()
        await client.aclose()
        with pytest.raises(ClientClosedError):
            await client.send_packet_to("ABCDEF", address)

    @use_asyncio_transport_xfail_uvloop
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

    @use_asyncio_transport_xfail_uvloop
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

    @use_asyncio_transport_xfail_uvloop
    @pytest.mark.parametrize("client", ["WITH_REMOTE"], indirect=True)
    async def test____recv_packet_from____ignore_other_socket_packets(
        self,
        client: AsyncUDPNetworkEndpoint[str, str],
        udp_socket_factory: Callable[[], Socket],
    ) -> None:
        other_client = udp_socket_factory()
        other_client.sendto(b"ABCDEF", client.get_local_address())
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(client.recv_packet_from(), timeout=0.1)

    async def test____recv_packet_from____closed_client(self, client: AsyncUDPNetworkEndpoint[str, str]) -> None:
        await client.aclose()
        with pytest.raises(ClientClosedError):
            await client.recv_packet_from()

    @use_asyncio_transport_xfail_uvloop
    async def test____recv_packet_from____invalid_data(self, client: AsyncUDPNetworkEndpoint[str, str], server: Socket) -> None:
        server.sendto("\u00E9".encode("latin-1"), client.get_local_address())
        with pytest.raises(DatagramProtocolParseError):
            await client.recv_packet_from()

    @use_asyncio_transport_xfail_uvloop
    async def test____iter_received_packets_from____yields_available_packets(
        self,
        client: AsyncUDPNetworkEndpoint[str, str],
        socket_family: int,
        server: Socket,
    ) -> None:
        server_address = new_socket_address(server.getsockname(), socket_family)
        for p in [b"A", b"B", b"C", b"D", b"E", b"F"]:
            server.sendto(p, client.get_local_address())

        close_task = asyncio.create_task(delay(client.aclose, 0.5))
        try:
            # NOTE: Comparison using set because equality check does not verify order
            assert {(p, addr) async for p, addr in client.iter_received_packets_from()} == {
                ("A", server_address),
                ("B", server_address),
                ("C", server_address),
                ("D", server_address),
                ("E", server_address),
                ("F", server_address),
            }
        finally:
            close_task.cancel()

    async def test____fileno____consistency(self, client: AsyncUDPNetworkEndpoint[str, str]) -> None:
        assert client.fileno() == client.socket.fileno()

    async def test____fileno____closed_client(self, client: AsyncUDPNetworkEndpoint[str, str]) -> None:
        await client.aclose()
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

    @pytest.mark.parametrize("client", ["WITHOUT_REMOTE"], indirect=True)
    async def test____get_remote_address____no_remote(
        self,
        client: AsyncUDPNetworkEndpoint[str, str],
    ) -> None:
        assert client.get_remote_address() is None

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
