from __future__ import annotations

import asyncio
import contextlib
import functools
from collections.abc import AsyncIterator, Awaitable, Callable
from socket import AF_INET, socket as Socket

from easynetwork.clients.async_udp import AsyncUDPNetworkClient
from easynetwork.exceptions import ClientClosedError, DatagramProtocolParseError
from easynetwork.lowlevel.api_async.backend._asyncio.datagram.endpoint import DatagramEndpoint, create_datagram_endpoint
from easynetwork.lowlevel.socket import IPv4SocketAddress, IPv6SocketAddress, SocketProxy
from easynetwork.protocol import DatagramProtocol

import pytest
import pytest_asyncio

from .....tools import PlatformMarkers
from .._utils import delay


@pytest.fixture
def udp_socket_factory(
    udp_socket_factory: Callable[[], Socket],
    localhost_ip: str,
) -> Callable[[], Socket]:

    @functools.wraps(udp_socket_factory)
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
        stack.enter_context(contextlib.suppress(OSError))

        async def factory() -> DatagramEndpoint:
            endpoint = await create_datagram_endpoint(
                family=socket_family,
                local_addr=(localhost_ip, 0),
            )
            stack.push_async_callback(lambda: asyncio.wait_for(endpoint.aclose(), 3))
            return endpoint

        yield factory


@pytest.mark.asyncio
@pytest.mark.flaky(retries=3, delay=0.1)
class TestAsyncUDPNetworkClient:
    @pytest_asyncio.fixture
    @staticmethod
    async def server(datagram_endpoint_factory: Callable[[], Awaitable[DatagramEndpoint]]) -> DatagramEndpoint:
        return await datagram_endpoint_factory()

    @pytest_asyncio.fixture
    @staticmethod
    async def client(
        server: DatagramEndpoint,
        udp_socket_factory: Callable[[], Socket],
        datagram_protocol: DatagramProtocol[str, str],
    ) -> AsyncIterator[AsyncUDPNetworkClient[str, str]]:
        remote_address: tuple[str, int] = server.get_extra_info("sockname")[:2]
        socket = udp_socket_factory()
        socket.connect(remote_address)

        async with AsyncUDPNetworkClient(socket, datagram_protocol, "asyncio") as client:
            assert client.is_connected()
            yield client

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

    @PlatformMarkers.runs_only_on_platform("linux", "Windows, MacOS and BSD-like do not raise error")
    async def test____send_packet____connection_refused(
        self,
        client: AsyncUDPNetworkClient[str, str],
        server: DatagramEndpoint,
    ) -> None:
        await server.aclose()
        with pytest.raises(ConnectionRefusedError):
            await client.send_packet("ABCDEF")

    @PlatformMarkers.runs_only_on_platform("linux", "Windows, MacOS and BSD-like do not raise error")
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

    @pytest.mark.parametrize("datagram_protocol", [pytest.param("bad_serialize", id="serializer_crash")], indirect=True)
    async def test____send_packet____protocol_crashed(
        self,
        client: AsyncUDPNetworkClient[str, str],
    ) -> None:
        with pytest.raises(RuntimeError, match=r"^protocol\.make_datagram\(\) crashed$"):
            await client.send_packet("ABCDEF")

    async def test____recv_packet____default(self, client: AsyncUDPNetworkClient[str, str], server: DatagramEndpoint) -> None:
        await server.sendto(b"ABCDEF", client.get_local_address())
        async with asyncio.timeout(3):
            assert await client.recv_packet() == "ABCDEF"

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

    async def test____recv_packet____invalid_data(
        self, client: AsyncUDPNetworkClient[str, str], server: DatagramEndpoint
    ) -> None:
        await server.sendto("\u00e9".encode("latin-1"), client.get_local_address())
        with pytest.raises(DatagramProtocolParseError):
            async with asyncio.timeout(3):
                await client.recv_packet()

    @pytest.mark.parametrize("datagram_protocol", [pytest.param("invalid", id="serializer_crash")], indirect=True)
    async def test____recv_packet____protocol_crashed(
        self,
        client: AsyncUDPNetworkClient[str, str],
        server: DatagramEndpoint,
    ) -> None:
        await server.sendto(b"ABCDEF", client.get_local_address())
        try:
            await client.recv_packet()
        except NotImplementedError:
            raise
        except Exception:
            with pytest.raises(RuntimeError, match=r"^protocol\.build_packet_from_datagram\(\) crashed$"):
                raise

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

    async def test____iter_received_packets____yields_available_packets_until_timeout(
        self,
        client: AsyncUDPNetworkClient[str, str],
        server: DatagramEndpoint,
    ) -> None:
        for p in [b"A", b"B", b"C", b"D", b"E", b"F"]:
            await server.sendto(p, client.get_local_address())

        # NOTE: Comparison using set because equality check does not verify order
        assert {p async for p in client.iter_received_packets(timeout=1)} == {"A", "B", "C", "D", "E", "F"}

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

        def __init__(self) -> None:
            super().__init__()
            self.connection_lost_event = asyncio.Event()

        def connection_made(self, transport: asyncio.DatagramTransport) -> None:  # type: ignore[override]
            self.transport = transport

        def connection_lost(self, exc: Exception | None) -> None:
            self.transport = None
            self.connection_lost_event.set()

        def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
            if self.transport is not None:
                self.transport.sendto(data, addr)

    @pytest_asyncio.fixture
    @classmethod
    async def server(
        cls,
        localhost_ip: str,
        socket_family: int,
    ) -> AsyncIterator[asyncio.DatagramTransport]:
        event_loop = asyncio.get_running_loop()

        transport, protocol = await event_loop.create_datagram_endpoint(
            cls.EchoProtocol,
            local_addr=(localhost_ip, 0),
            family=socket_family,
        )
        try:
            with contextlib.closing(transport):
                await asyncio.sleep(0.01)
                yield transport
        finally:
            await protocol.connection_lost_event.wait()

    @pytest.fixture
    @staticmethod
    def remote_address(server: asyncio.DatagramTransport) -> tuple[str, int]:
        return server.get_extra_info("sockname")[:2]

    async def test____dunder_init____automatic_local_address(
        self,
        remote_address: tuple[str, int],
        datagram_protocol: DatagramProtocol[str, str],
    ) -> None:
        async with AsyncUDPNetworkClient(remote_address, datagram_protocol, "asyncio") as client:
            assert client.is_connected()
            assert client.get_local_address().host in {"127.0.0.1", "::1"}
            assert client.get_local_address().port > 0

            await client.send_packet("Test")
            assert await client.recv_packet() == "Test"

    async def test____dunder_init____with_local_address(
        self,
        localhost_ip: str,
        remote_address: tuple[str, int],
        datagram_protocol: DatagramProtocol[str, str],
    ) -> None:
        async with AsyncUDPNetworkClient(remote_address, datagram_protocol, "asyncio", local_address=(localhost_ip, 0)) as client:
            assert client.is_connected()
            assert client.get_local_address().host == localhost_ip
            assert client.get_local_address().port > 0

            await client.send_packet("Test")
            assert await client.recv_packet() == "Test"

    async def test____dunder_init____remote_address____not_set(
        self,
        udp_socket_factory: Callable[[], Socket],
        datagram_protocol: DatagramProtocol[str, str],
    ) -> None:
        with pytest.raises(OSError):
            _ = AsyncUDPNetworkClient(udp_socket_factory(), datagram_protocol, "asyncio")

    async def test____wait_connected____idempotent(
        self,
        remote_address: tuple[str, int],
        datagram_protocol: DatagramProtocol[str, str],
    ) -> None:
        async with contextlib.aclosing(AsyncUDPNetworkClient(remote_address, datagram_protocol, "asyncio")) as client:
            await client.wait_connected()
            assert client.is_connected()
            await client.wait_connected()
            assert client.is_connected()

    async def test____wait_connected____simultaneous(
        self,
        remote_address: tuple[str, int],
        datagram_protocol: DatagramProtocol[str, str],
    ) -> None:
        async with contextlib.aclosing(AsyncUDPNetworkClient(remote_address, datagram_protocol, "asyncio")) as client:
            await asyncio.gather(*[client.wait_connected() for _ in range(5)])
            assert client.is_connected()

    async def test____wait_connected____is_closing____connection_not_performed_yet(
        self,
        remote_address: tuple[str, int],
        datagram_protocol: DatagramProtocol[str, str],
    ) -> None:
        async with contextlib.aclosing(AsyncUDPNetworkClient(remote_address, datagram_protocol, "asyncio")) as client:
            assert not client.is_connected()
            assert not client.is_closing()
            await client.wait_connected()
            assert client.is_connected()
            assert not client.is_closing()

    async def test____wait_connected____close_before_trying_to_connect(
        self,
        remote_address: tuple[str, int],
        datagram_protocol: DatagramProtocol[str, str],
    ) -> None:
        client = AsyncUDPNetworkClient(remote_address, datagram_protocol, "asyncio")
        await client.aclose()
        with pytest.raises(ClientClosedError):
            await client.wait_connected()

    async def test____socket_property____connection_not_performed_yet(
        self,
        remote_address: tuple[str, int],
        datagram_protocol: DatagramProtocol[str, str],
    ) -> None:
        async with contextlib.aclosing(AsyncUDPNetworkClient(remote_address, datagram_protocol, "asyncio")) as client:
            with pytest.raises(AttributeError):
                _ = client.socket

            await client.wait_connected()

            assert isinstance(client.socket, SocketProxy)
            assert client.socket is client.socket

    async def test____get_local_address____connection_not_performed_yet(
        self,
        remote_address: tuple[str, int],
        datagram_protocol: DatagramProtocol[str, str],
    ) -> None:
        async with contextlib.aclosing(AsyncUDPNetworkClient(remote_address, datagram_protocol, "asyncio")) as client:
            with pytest.raises(OSError):
                _ = client.get_local_address()

            await client.wait_connected()

            _ = client.get_local_address()

    async def test____get_remote_address____connection_not_performed_yet(
        self,
        remote_address: tuple[str, int],
        datagram_protocol: DatagramProtocol[str, str],
    ) -> None:
        async with contextlib.aclosing(AsyncUDPNetworkClient(remote_address, datagram_protocol, "asyncio")) as client:
            with pytest.raises(OSError):
                _ = client.get_remote_address()

            await client.wait_connected()

            assert client.get_remote_address()[:2] == remote_address

    async def test____send_packet____recv_packet____implicit_connection(
        self,
        remote_address: tuple[str, int],
        datagram_protocol: DatagramProtocol[str, str],
    ) -> None:
        async with contextlib.aclosing(AsyncUDPNetworkClient(remote_address, datagram_protocol, "asyncio")) as client:
            assert not client.is_connected()

            async with asyncio.timeout(3):
                await client.send_packet("Connected")
                assert await client.recv_packet() == "Connected"

            assert client.is_connected()
