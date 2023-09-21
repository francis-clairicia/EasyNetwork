from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable
from socket import AF_INET, socket as Socket
from typing import Any

from easynetwork.api_async.client.udp import AsyncUDPNetworkClient, AsyncUDPNetworkEndpoint
from easynetwork.exceptions import ClientClosedError, DatagramProtocolParseError
from easynetwork.protocol import DatagramProtocol
from easynetwork.tools.socket import IPv4SocketAddress, IPv6SocketAddress, SocketProxy, new_socket_address
from easynetwork_asyncio.datagram.endpoint import DatagramEndpoint, create_datagram_endpoint

import pytest
import pytest_asyncio

from .....tools import PlatformMarkers
from .._utils import delay
from ..conftest import use_asyncio_transport_xfail_uvloop


@pytest.fixture
def udp_socket_factory(
    request: pytest.FixtureRequest,
    localhost_ip: str,
) -> Callable[[], Socket]:
    udp_socket_factory: Callable[[], Socket] = request.getfixturevalue("udp_socket_factory")

    def bound_udp_socket_factory() -> Socket:
        sock = udp_socket_factory()
        sock.settimeout(3)
        sock.bind((localhost_ip, 0))
        return sock

    return bound_udp_socket_factory


@pytest_asyncio.fixture
async def datagram_endpoint_factory(
    socket_family: int,
    localhost_ip: str,
) -> AsyncIterator[Callable[[], Awaitable[DatagramEndpoint]]]:
    async with contextlib.AsyncExitStack() as stack:

        async def factory() -> DatagramEndpoint:
            endpoint = await create_datagram_endpoint(
                family=socket_family,
                local_addr=(localhost_ip, 0),
            )
            stack.push_async_callback(lambda: asyncio.wait_for(endpoint.wait_closed(), 3))
            stack.callback(endpoint.close)
            return endpoint

        yield factory


@pytest.mark.asyncio
class TestAsyncUDPNetworkClient:
    @pytest_asyncio.fixture
    @staticmethod
    async def server(datagram_endpoint_factory: Callable[[], Awaitable[DatagramEndpoint]]) -> DatagramEndpoint:
        return await datagram_endpoint_factory()

    @pytest.fixture
    @staticmethod
    def remote_address(server: DatagramEndpoint) -> tuple[str, int]:
        return server.get_extra_info("sockname")[:2]

    @pytest.fixture(params=[False, True], ids=lambda boolean: f"use_external_socket=={boolean}")
    @staticmethod
    def use_external_socket(request: pytest.FixtureRequest, udp_socket_factory: Callable[[], Socket]) -> Socket | None:
        use_external_socket: bool = getattr(request, "param")
        if use_external_socket:
            return udp_socket_factory()
        return None

    @pytest_asyncio.fixture
    @staticmethod
    async def client(
        remote_address: tuple[str, int],
        use_external_socket: Socket | None,
        datagram_protocol: DatagramProtocol[str, str],
        use_asyncio_transport: bool,
    ) -> AsyncIterator[AsyncUDPNetworkClient[str, str]]:
        if use_external_socket is not None:
            use_external_socket.connect(remote_address)
            client = AsyncUDPNetworkClient(
                use_external_socket, datagram_protocol, backend_kwargs={"transport": use_asyncio_transport}
            )
        else:
            client = AsyncUDPNetworkClient(remote_address, datagram_protocol, backend_kwargs={"transport": use_asyncio_transport})
        async with client:
            assert client.is_connected()
            yield client

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

    async def test____send_packet____default(self, client: AsyncUDPNetworkClient[str, str], server: DatagramEndpoint) -> None:
        await client.send_packet("ABCDEF")
        async with asyncio.timeout(3):
            assert await server.recvfrom() == (b"ABCDEF", client.get_local_address())

    # Windows and MacOS do not raise error
    @PlatformMarkers.skipif_platform_win32
    @PlatformMarkers.skipif_platform_macOS
    async def test____send_packet____connection_refused(
        self,
        client: AsyncUDPNetworkClient[str, str],
        server: DatagramEndpoint,
    ) -> None:
        await server.aclose()
        with pytest.raises(ConnectionRefusedError):
            await client.send_packet("ABCDEF")

    # Windows and MacOS do not raise error
    @PlatformMarkers.skipif_platform_win32
    @PlatformMarkers.skipif_platform_macOS
    async def test____send_packet____connection_refused____after_previous_successful_try(
        self,
        client: AsyncUDPNetworkClient[str, str],
        server: DatagramEndpoint,
    ) -> None:
        await client.send_packet("ABC")
        async with asyncio.timeout(3):
            assert await server.recvfrom() == (b"ABC", client.get_local_address())
        await server.aclose()
        with pytest.raises(ConnectionRefusedError):
            await client.send_packet("DEF")

    async def test____send_packet____closed_client(self, client: AsyncUDPNetworkClient[str, str]) -> None:
        await client.aclose()
        with pytest.raises(ClientClosedError):
            await client.send_packet("ABCDEF")

    @use_asyncio_transport_xfail_uvloop
    async def test____recv_packet____default(self, client: AsyncUDPNetworkClient[str, str], server: DatagramEndpoint) -> None:
        await server.sendto(b"ABCDEF", client.get_local_address())
        async with asyncio.timeout(3):
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
    async def test____recv_packet____invalid_data(
        self, client: AsyncUDPNetworkClient[str, str], server: DatagramEndpoint
    ) -> None:
        await server.sendto("\u00E9".encode("latin-1"), client.get_local_address())
        with pytest.raises(DatagramProtocolParseError):
            async with asyncio.timeout(3):
                await client.recv_packet()

    @use_asyncio_transport_xfail_uvloop
    async def test____iter_received_packets____yields_available_packets_until_close(
        self,
        client: AsyncUDPNetworkClient[str, str],
        server: DatagramEndpoint,
    ) -> None:
        for p in [b"A", b"B", b"C", b"D", b"E", b"F"]:
            await server.sendto(p, client.get_local_address())

        close_task = asyncio.create_task(delay(client.aclose, 0.5))
        await asyncio.sleep(0)
        try:
            # NOTE: Comparison using set because equality check does not verify order
            assert {p async for p in client.iter_received_packets(timeout=None)} == {"A", "B", "C", "D", "E", "F"}
        finally:
            close_task.cancel()
            await asyncio.wait({close_task})

    @use_asyncio_transport_xfail_uvloop
    async def test____iter_received_packets____yields_available_packets_within_given_timeout(
        self,
        client: AsyncUDPNetworkClient[str, str],
        server: DatagramEndpoint,
    ) -> None:
        async def send_coro() -> None:
            await server.sendto(b"A", client.get_local_address())
            await asyncio.sleep(0.1)
            await server.sendto(b"B", client.get_local_address())
            await asyncio.sleep(0.4)
            await server.sendto(b"C", client.get_local_address())
            await asyncio.sleep(0.2)
            await server.sendto(b"D", client.get_local_address())
            await asyncio.sleep(0.5)
            await server.sendto(b"E", client.get_local_address())

        send_task = asyncio.create_task(send_coro())
        try:
            assert [p async for p in client.iter_received_packets(timeout=1)] == ["A", "B", "C", "D"]
        finally:
            send_task.cancel()
            await asyncio.wait({send_task})

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

        def __init__(self, connection_lost_future: asyncio.Future[None]) -> None:
            super().__init__()
            self.connection_lost_future: asyncio.Future[None] = connection_lost_future

        def connection_made(self, transport: asyncio.DatagramTransport) -> None:  # type: ignore[override]
            self.transport = transport

        def connection_lost(self, exc: Exception | None) -> None:
            self.transport = None
            self.connection_lost_future.set_result(None)

        def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
            if self.transport is not None:
                self.transport.sendto(data, addr)

    @pytest_asyncio.fixture
    @classmethod
    async def server(
        cls,
        event_loop: asyncio.AbstractEventLoop,
        localhost_ip: str,
        socket_family: int,
    ) -> AsyncIterator[asyncio.DatagramTransport]:
        transport, protocol = await event_loop.create_datagram_endpoint(
            lambda: cls.EchoProtocol(event_loop.create_future()),
            local_addr=(localhost_ip, 0),
            family=socket_family,
        )
        try:
            await asyncio.sleep(0.01)
            yield transport
        finally:
            transport.close()
            await protocol.connection_lost_future

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
        backend_kwargs: dict[str, Any],
    ) -> None:
        async with contextlib.aclosing(
            AsyncUDPNetworkClient(
                remote_address,
                datagram_protocol,
                backend_kwargs=backend_kwargs,
            )
        ) as client:
            await client.wait_connected()
            assert client.is_connected()
            await client.wait_connected()
            assert client.is_connected()

    async def test____wait_connected____simultaneous(
        self,
        remote_address: tuple[str, int],
        datagram_protocol: DatagramProtocol[str, str],
        backend_kwargs: dict[str, Any],
    ) -> None:
        async with contextlib.aclosing(
            AsyncUDPNetworkClient(
                remote_address,
                datagram_protocol,
                backend_kwargs=backend_kwargs,
            )
        ) as client:
            await asyncio.gather(*[client.wait_connected() for _ in range(5)])
            assert client.is_connected()

    async def test____wait_connected____is_closing____connection_not_performed_yet(
        self,
        remote_address: tuple[str, int],
        datagram_protocol: DatagramProtocol[str, str],
        backend_kwargs: dict[str, Any],
    ) -> None:
        async with contextlib.aclosing(
            AsyncUDPNetworkClient(
                remote_address,
                datagram_protocol,
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
        backend_kwargs: dict[str, Any],
    ) -> None:
        async with contextlib.aclosing(
            AsyncUDPNetworkClient(
                remote_address,
                datagram_protocol,
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
        backend_kwargs: dict[str, Any],
    ) -> None:
        async with contextlib.aclosing(
            AsyncUDPNetworkClient(
                remote_address,
                datagram_protocol,
                backend_kwargs=backend_kwargs,
            )
        ) as client:
            with pytest.raises(AttributeError):
                _ = client.socket

            await client.wait_connected()

            assert isinstance(client.socket, SocketProxy)

    async def test____get_local_address____connection_not_performed_yet(
        self,
        remote_address: tuple[str, int],
        datagram_protocol: DatagramProtocol[str, str],
        backend_kwargs: dict[str, Any],
    ) -> None:
        async with contextlib.aclosing(
            AsyncUDPNetworkClient(
                remote_address,
                datagram_protocol,
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
        backend_kwargs: dict[str, Any],
    ) -> None:
        async with contextlib.aclosing(
            AsyncUDPNetworkClient(
                remote_address,
                datagram_protocol,
                backend_kwargs=backend_kwargs,
            )
        ) as client:
            with pytest.raises(OSError):
                _ = client.get_remote_address()

            await client.wait_connected()

            assert client.get_remote_address()[:2] == remote_address

    @use_asyncio_transport_xfail_uvloop
    async def test____send_packet____recv_packet____implicit_connection(
        self,
        remote_address: tuple[str, int],
        datagram_protocol: DatagramProtocol[str, str],
        backend_kwargs: dict[str, Any],
    ) -> None:
        async with contextlib.aclosing(
            AsyncUDPNetworkClient(
                remote_address,
                datagram_protocol,
                backend_kwargs=backend_kwargs,
            )
        ) as client:
            assert not client.is_connected()

            async with asyncio.timeout(3):
                await client.send_packet("Connected")
                assert await client.recv_packet() == "Connected"

            assert client.is_connected()


@pytest.mark.asyncio
class TestAsyncUDPNetworkEndpoint:
    @pytest_asyncio.fixture
    @staticmethod
    async def server(datagram_endpoint_factory: Callable[[], Awaitable[DatagramEndpoint]]) -> DatagramEndpoint:
        return await datagram_endpoint_factory()

    @pytest.fixture
    @staticmethod
    def remote_address(server: DatagramEndpoint) -> tuple[str, int]:
        return server.get_extra_info("sockname")[:2]

    @pytest_asyncio.fixture(params=["WITH_REMOTE", "WITHOUT_REMOTE"])
    @staticmethod
    async def client(
        request: pytest.FixtureRequest,
        remote_address: tuple[str, int],
        localhost_ip: str,
        datagram_protocol: DatagramProtocol[str, str],
        use_asyncio_transport: bool,
    ) -> AsyncIterator[AsyncUDPNetworkEndpoint[str, str]]:
        address: tuple[str, int] | None
        match getattr(request, "param"):
            case "WITH_REMOTE":
                address = remote_address
            case "WITHOUT_REMOTE":
                address = None
            case invalid:
                pytest.fail(f"Invalid fixture param, got {invalid!r}")
        async with AsyncUDPNetworkEndpoint(
            datagram_protocol,
            remote_address=address,
            local_address=(localhost_ip, 0),
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
        datagram_endpoint_factory: Callable[[], Awaitable[DatagramEndpoint]],
    ) -> None:
        async with asyncio.timeout(3):
            other_client_1 = await datagram_endpoint_factory()
            other_client_2 = await datagram_endpoint_factory()
            other_client_3 = await datagram_endpoint_factory()
            for other_client in [other_client_1, other_client_2, other_client_3]:
                await client.send_packet_to("ABCDEF", other_client.get_extra_info("sockname"))
                assert await other_client.recvfrom() == (b"ABCDEF", client.get_local_address())

    @pytest.mark.parametrize("client", ["WITHOUT_REMOTE"], indirect=True)
    async def test____send_packet_to____None_is_invalid(self, client: AsyncUDPNetworkEndpoint[str, str]) -> None:
        with pytest.raises(ValueError):
            await client.send_packet_to("ABCDEF", None)

    @pytest.mark.parametrize("client", ["WITH_REMOTE"], indirect=True)
    async def test____send_packet_to____send_to_connected_address____via_None(
        self,
        client: AsyncUDPNetworkEndpoint[str, str],
        server: DatagramEndpoint,
    ) -> None:
        async with asyncio.timeout(3):
            await client.send_packet_to("ABCDEF", None)
            assert await server.recvfrom() == (b"ABCDEF", client.get_local_address())

    @pytest.mark.parametrize("client", ["WITH_REMOTE"], indirect=True)
    async def test____send_packet_to____send_to_connected_address____explicit(
        self,
        client: AsyncUDPNetworkEndpoint[str, str],
        server: DatagramEndpoint,
        remote_address: tuple[str, int],
    ) -> None:
        async with asyncio.timeout(3):
            await client.send_packet_to("ABCDEF", remote_address)
            assert await server.recvfrom() == (b"ABCDEF", client.get_local_address())

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
        self, client: AsyncUDPNetworkEndpoint[str, str], datagram_endpoint_factory: Callable[[], Awaitable[DatagramEndpoint]]
    ) -> None:
        async with asyncio.timeout(3):
            other_client = await datagram_endpoint_factory()
            other_client_address = other_client.get_extra_info("sockname")

            if client.get_remote_address() is None:
                # Even if other socket is closed, there should be no error

                await other_client.aclose()

                await client.send_packet_to("ABCDEF", other_client_address)
            else:
                # The given address is not the configured remote address
                with pytest.raises(ValueError):
                    await client.send_packet_to("ABCDEF", other_client_address)

    # Windows and MacOS do not raise error
    @PlatformMarkers.skipif_platform_win32
    @PlatformMarkers.skipif_platform_macOS
    @pytest.mark.parametrize("client", ["WITH_REMOTE"], indirect=True)
    async def test____send_packet_to____connection_refused(
        self,
        client: AsyncUDPNetworkEndpoint[str, str],
        server: DatagramEndpoint,
    ) -> None:
        await server.aclose()
        async with asyncio.timeout(3):
            with pytest.raises(ConnectionRefusedError):
                await client.send_packet_to("ABCDEF", None)

    # Windows and MacOS do not raise error
    @PlatformMarkers.skipif_platform_win32
    @PlatformMarkers.skipif_platform_macOS
    @pytest.mark.parametrize("client", ["WITH_REMOTE"], indirect=True)
    async def test____send_packet_to____connection_refused____after_previous_successful_try(
        self,
        client: AsyncUDPNetworkEndpoint[str, str],
        server: DatagramEndpoint,
    ) -> None:
        async with asyncio.timeout(3):
            await client.send_packet_to("ABC", None)
            assert await server.recvfrom() == (b"ABC", client.get_local_address())
            await server.aclose()
            with pytest.raises(ConnectionRefusedError):
                await client.send_packet_to("DEF", None)

    async def test____send_packet_to____closed_client(
        self,
        client: AsyncUDPNetworkEndpoint[str, str],
        remote_address: tuple[str, int],
    ) -> None:
        await client.aclose()
        with pytest.raises(ClientClosedError):
            await client.send_packet_to("ABCDEF", remote_address)

    @use_asyncio_transport_xfail_uvloop
    @pytest.mark.parametrize("client", ["WITHOUT_REMOTE"], indirect=True)
    async def test____recv_packet_from____receive_from_anyone(
        self,
        client: AsyncUDPNetworkEndpoint[str, str],
        socket_family: int,
        datagram_endpoint_factory: Callable[[], Awaitable[DatagramEndpoint]],
    ) -> None:
        async with asyncio.timeout(3):
            other_client_1 = await datagram_endpoint_factory()
            other_client_2 = await datagram_endpoint_factory()
            other_client_3 = await datagram_endpoint_factory()
            for other_client in [other_client_1, other_client_2, other_client_3]:
                await other_client.sendto(b"ABCDEF", client.get_local_address())
                packet, sender = await client.recv_packet_from()
                assert packet == "ABCDEF"
                if socket_family == AF_INET:
                    assert isinstance(sender, IPv4SocketAddress)
                else:
                    assert isinstance(sender, IPv6SocketAddress)
                assert sender == new_socket_address(other_client.get_extra_info("sockname"), socket_family)

    @use_asyncio_transport_xfail_uvloop
    @pytest.mark.parametrize("client", ["WITH_REMOTE"], indirect=True)
    async def test____recv_packet_from____receive_from_remote(
        self,
        client: AsyncUDPNetworkEndpoint[str, str],
        server: DatagramEndpoint,
        socket_family: int,
    ) -> None:
        async with asyncio.timeout(3):
            await server.sendto(b"ABCDEF", client.get_local_address())
            packet, sender = await client.recv_packet_from()
            assert packet == "ABCDEF"
            if socket_family == AF_INET:
                assert isinstance(sender, IPv4SocketAddress)
            else:
                assert isinstance(sender, IPv6SocketAddress)
            assert sender == new_socket_address(server.get_extra_info("sockname"), socket_family)

    @use_asyncio_transport_xfail_uvloop
    @pytest.mark.parametrize("client", ["WITH_REMOTE"], indirect=True)
    async def test____recv_packet_from____ignore_other_socket_packets(
        self,
        client: AsyncUDPNetworkEndpoint[str, str],
        udp_socket_factory: Callable[[], Socket],
    ) -> None:
        async with asyncio.timeout(3):
            other_client = udp_socket_factory()
            other_client.sendto(b"ABCDEF", client.get_local_address())
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(client.recv_packet_from(), timeout=0.1)

    async def test____recv_packet_from____closed_client(self, client: AsyncUDPNetworkEndpoint[str, str]) -> None:
        await client.aclose()
        with pytest.raises(ClientClosedError):
            await client.recv_packet_from()

    @use_asyncio_transport_xfail_uvloop
    async def test____recv_packet_from____invalid_data(
        self,
        client: AsyncUDPNetworkEndpoint[str, str],
        server: DatagramEndpoint,
    ) -> None:
        async with asyncio.timeout(3):
            await server.sendto("\u00E9".encode("latin-1"), client.get_local_address())
            with pytest.raises(DatagramProtocolParseError):
                await client.recv_packet_from()

    @use_asyncio_transport_xfail_uvloop
    async def test____iter_received_packets_from____yields_available_packets(
        self,
        client: AsyncUDPNetworkEndpoint[str, str],
        socket_family: int,
        server: DatagramEndpoint,
        remote_address: tuple[str, int],
    ) -> None:
        async with asyncio.timeout(3):
            expected_server_address = new_socket_address(remote_address, socket_family)
            for p in [b"A", b"B", b"C", b"D", b"E", b"F"]:
                await server.sendto(p, client.get_local_address())

            close_task = asyncio.create_task(delay(client.aclose, 0.5))
            await asyncio.sleep(0)
            try:
                # NOTE: Comparison using set because equality check does not verify order
                assert {(p, addr) async for p, addr in client.iter_received_packets_from(timeout=None)} == {
                    ("A", expected_server_address),
                    ("B", expected_server_address),
                    ("C", expected_server_address),
                    ("D", expected_server_address),
                    ("E", expected_server_address),
                    ("F", expected_server_address),
                }
            finally:
                close_task.cancel()
                await asyncio.wait({close_task})

    @use_asyncio_transport_xfail_uvloop
    async def test____iter_received_packets____yields_available_packets_within_given_timeout(
        self,
        client: AsyncUDPNetworkEndpoint[str, str],
        server: DatagramEndpoint,
    ) -> None:
        async def send_coro() -> None:
            await server.sendto(b"A", client.get_local_address())
            await asyncio.sleep(0.1)
            await server.sendto(b"B", client.get_local_address())
            await asyncio.sleep(0.4)
            await server.sendto(b"C", client.get_local_address())
            await asyncio.sleep(0.2)
            await server.sendto(b"D", client.get_local_address())
            await asyncio.sleep(0.5)
            await server.sendto(b"E", client.get_local_address())

        send_task = asyncio.create_task(send_coro())
        try:
            assert [p async for p, _ in client.iter_received_packets_from(timeout=1)] == ["A", "B", "C", "D"]
        finally:
            send_task.cancel()
            await asyncio.wait({send_task})

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
