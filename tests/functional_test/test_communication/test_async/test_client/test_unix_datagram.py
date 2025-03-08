from __future__ import annotations

import asyncio
import contextlib
import functools
import inspect
import pathlib
from collections.abc import AsyncIterator, Awaitable, Callable
from socket import socket as Socket
from typing import Any

from easynetwork.clients.async_unix_datagram import AsyncUnixDatagramClient
from easynetwork.exceptions import ClientClosedError, DatagramProtocolParseError
from easynetwork.lowlevel.api_async.backend._asyncio.datagram.endpoint import DatagramEndpoint, create_datagram_endpoint
from easynetwork.lowlevel.socket import SocketProxy, UnixSocketAddress
from easynetwork.protocol import DatagramProtocol

import pytest
import pytest_asyncio

from .....pytest_plugins.unix_sockets import UnixSocketPathFactory
from .....tools import PlatformMarkers, is_uvloop_event_loop
from .._utils import delay


@pytest.fixture
def unix_datagram_socket_factory(
    request: pytest.FixtureRequest,
    event_loop: asyncio.AbstractEventLoop,
    unix_datagram_socket_factory: Callable[[], Socket],
    unix_socket_path_factory: UnixSocketPathFactory,
) -> Callable[[], Socket]:

    from easynetwork.lowlevel import _unix_utils

    @functools.wraps(unix_datagram_socket_factory)
    def bound_unix_datagram_socket_factory() -> Socket:
        sock = unix_datagram_socket_factory()
        sock.settimeout(3)
        match getattr(request, "param", None):
            case "PATHNAME":
                sock.bind(unix_socket_path_factory(reuse_old_socket=False))
            case "ABSTRACT":
                if is_uvloop_event_loop(event_loop):
                    # Addresses received through uvloop transports contains extra NULL bytes because the creation of
                    # the bytes object from the sockaddr_un structure does not take into account the real addrlen.
                    # https://github.com/MagicStack/uvloop/blob/v0.21.0/uvloop/includes/compat.h#L34-L55
                    sock.close()
                    pytest.xfail("uvloop translation of abstract unix sockets to python object is wrong.")
                sock.bind("")
            case None:
                if _unix_utils.platform_supports_automatic_socket_bind() and not is_uvloop_event_loop(event_loop):
                    sock.bind("")
                else:
                    sock.bind(unix_socket_path_factory(reuse_old_socket=False))
            case _:
                sock.close()
                pytest.fail(f"Invalid use_unix_address_type parameter: {request.param}")
        return sock

    return bound_unix_datagram_socket_factory


@pytest_asyncio.fixture
async def datagram_endpoint_factory(
    unix_datagram_socket_factory: Callable[[], Socket],
) -> AsyncIterator[Callable[[], Awaitable[DatagramEndpoint]]]:
    async with contextlib.AsyncExitStack() as stack:
        stack.enter_context(contextlib.suppress(OSError))

        async def factory() -> DatagramEndpoint:
            # Caveat: uvloop does not support having a UNIX socket address for "local_addr" parameter.
            # The socket must be created manually.
            sock = unix_datagram_socket_factory()
            sock.setblocking(False)
            endpoint = await create_datagram_endpoint(sock=sock)
            stack.push_async_callback(lambda: asyncio.wait_for(endpoint.aclose(), 3))
            return endpoint

        yield factory


@pytest.mark.asyncio
@pytest.mark.flaky(retries=3, delay=0.1)
@PlatformMarkers.skipif_platform_win32
class TestAsyncUnixDatagramClient:
    @pytest_asyncio.fixture
    @staticmethod
    async def server(datagram_endpoint_factory: Callable[[], Awaitable[DatagramEndpoint]]) -> DatagramEndpoint:
        return await datagram_endpoint_factory()

    @pytest_asyncio.fixture
    @staticmethod
    async def client(
        server: DatagramEndpoint,
        unix_datagram_socket_factory: Callable[[], Socket],
        datagram_protocol: DatagramProtocol[str, str],
    ) -> AsyncIterator[AsyncUnixDatagramClient[str, str]]:
        remote_address: str | bytes = server.get_extra_info("sockname")
        socket = unix_datagram_socket_factory()
        socket.connect(remote_address)

        async with AsyncUnixDatagramClient(socket, datagram_protocol, "asyncio") as client:
            assert client.is_connected()
            yield client

    @pytest.mark.parametrize(
        "unix_datagram_socket_factory",
        [
            pytest.param("PATHNAME"),
            pytest.param("ABSTRACT", marks=PlatformMarkers.supports_abstract_sockets),
        ],
        indirect=True,
    )
    async def test____aclose____idempotent(self, client: AsyncUnixDatagramClient[str, str]) -> None:
        assert not client.is_closing()
        await client.aclose()
        assert client.is_closing()
        await client.aclose()
        assert client.is_closing()

    async def test____send_packet____default(self, client: AsyncUnixDatagramClient[str, str], server: DatagramEndpoint) -> None:
        await client.send_packet("ABCDEF")
        async with asyncio.timeout(3):
            assert await server.recvfrom() == (b"ABCDEF", client.get_local_name().as_raw())

    async def test____send_packet____closed_client(self, client: AsyncUnixDatagramClient[str, str]) -> None:
        await client.aclose()
        with pytest.raises(ClientClosedError):
            await client.send_packet("ABCDEF")

    @pytest.mark.parametrize("datagram_protocol", [pytest.param("bad_serialize", id="serializer_crash")], indirect=True)
    async def test____send_packet____protocol_crashed(
        self,
        client: AsyncUnixDatagramClient[str, str],
    ) -> None:
        with pytest.raises(RuntimeError, match=r"^protocol\.make_datagram\(\) crashed$"):
            await client.send_packet("ABCDEF")

    async def test____recv_packet____default(self, client: AsyncUnixDatagramClient[str, str], server: DatagramEndpoint) -> None:
        await server.sendto(b"ABCDEF", client.get_local_name().as_raw())
        async with asyncio.timeout(3):
            assert await client.recv_packet() == "ABCDEF"

    async def test____recv_packet____closed_client(self, client: AsyncUnixDatagramClient[str, str]) -> None:
        await client.aclose()
        with pytest.raises(ClientClosedError):
            await client.recv_packet()

    async def test____recv_packet____invalid_data(
        self, client: AsyncUnixDatagramClient[str, str], server: DatagramEndpoint
    ) -> None:
        await server.sendto("\u00e9".encode("latin-1"), client.get_local_name().as_raw())
        with pytest.raises(DatagramProtocolParseError):
            async with asyncio.timeout(3):
                await client.recv_packet()

    @pytest.mark.parametrize("datagram_protocol", [pytest.param("invalid", id="serializer_crash")], indirect=True)
    async def test____recv_packet____protocol_crashed(
        self,
        client: AsyncUnixDatagramClient[str, str],
        server: DatagramEndpoint,
    ) -> None:
        await server.sendto(b"ABCDEF", client.get_local_name().as_raw())
        try:
            await client.recv_packet()
        except NotImplementedError:
            raise
        except Exception:
            with pytest.raises(RuntimeError, match=r"^protocol\.build_packet_from_datagram\(\) crashed$"):
                raise

    async def test____iter_received_packets____yields_available_packets_until_close(
        self,
        client: AsyncUnixDatagramClient[str, str],
        server: DatagramEndpoint,
    ) -> None:
        for p in [b"A", b"B", b"C", b"D", b"E", b"F"]:
            await server.sendto(p, client.get_local_name().as_raw())

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
        client: AsyncUnixDatagramClient[str, str],
        server: DatagramEndpoint,
    ) -> None:
        for p in [b"A", b"B", b"C", b"D", b"E", b"F"]:
            await server.sendto(p, client.get_local_name().as_raw())

        # NOTE: Comparison using set because equality check does not verify order
        assert {p async for p in client.iter_received_packets(timeout=1)} == {"A", "B", "C", "D", "E", "F"}

    async def test____get_local_name____consistency(self, client: AsyncUnixDatagramClient[str, str]) -> None:
        address = client.get_local_name()
        assert isinstance(address, UnixSocketAddress)
        assert address.as_raw() == client.socket.getsockname()

    async def test____get_peer_name____consistency(self, client: AsyncUnixDatagramClient[str, str]) -> None:
        address = client.get_peer_name()
        assert isinstance(address, UnixSocketAddress)
        assert address.as_raw() == client.socket.getpeername()


@pytest.mark.asyncio
@PlatformMarkers.skipif_platform_win32
class TestAsyncUnixDatagramClientConnection:
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

        def datagram_received(self, data: bytes, addr: Any) -> None:
            if self.transport is not None:
                self.transport.sendto(data, addr)

    @pytest_asyncio.fixture
    @classmethod
    async def server(
        cls,
        unix_datagram_socket_factory: Callable[[], Socket],
    ) -> AsyncIterator[asyncio.DatagramTransport]:
        event_loop = asyncio.get_running_loop()

        # Caveat: uvloop does not support having a UNIX socket address for "local_addr" parameter.
        # The socket must be created manually.
        sock = unix_datagram_socket_factory()
        sock.setblocking(False)
        transport, protocol = await event_loop.create_datagram_endpoint(cls.EchoProtocol, sock=sock)
        del sock
        try:
            with contextlib.closing(transport):
                await asyncio.sleep(0.01)
                yield transport
        finally:
            await protocol.connection_lost_event.wait()

    @pytest.fixture
    @staticmethod
    def remote_address(server: asyncio.DatagramTransport) -> str | bytes:
        return server.get_extra_info("sockname")

    @pytest.fixture
    @staticmethod
    def local_path(unix_socket_path_factory: UnixSocketPathFactory) -> str:
        return unix_socket_path_factory()

    @PlatformMarkers.supports_abstract_sockets
    async def test____dunder_init____automatic_local_name(
        self,
        remote_address: str | bytes,
        datagram_protocol: DatagramProtocol[str, str],
    ) -> None:
        event_loop = asyncio.get_running_loop()
        if is_uvloop_event_loop(event_loop):
            # Addresses received through uvloop transports contains extra NULL bytes because the creation of
            # the bytes object from the sockaddr_un structure does not take into account the real addrlen.
            # https://github.com/MagicStack/uvloop/blob/v0.21.0/uvloop/includes/compat.h#L34-L55
            pytest.xfail("uvloop translation of abstract unix sockets to python object is wrong.")

        async with AsyncUnixDatagramClient(remote_address, datagram_protocol, "asyncio") as client:
            assert client.is_connected()
            assert not client.get_local_name().is_unnamed()

            async with asyncio.timeout(3):
                await client.send_packet("Test")
                assert await client.recv_packet() == "Test"

    @PlatformMarkers.abstract_sockets_unsupported
    async def test____dunder_init____automatic_local_name____unsupported_by_current_platform(
        self,
        remote_address: str | bytes,
        datagram_protocol: DatagramProtocol[str, str],
    ) -> None:
        with pytest.raises(
            ValueError,
            match=r"^local_path parameter is required on this platform and cannot be an empty string\.",
        ):
            _ = AsyncUnixDatagramClient(remote_address, datagram_protocol, "asyncio")

    async def test____dunder_init____with_local_name(
        self,
        local_path: str,
        remote_address: str | bytes,
        datagram_protocol: DatagramProtocol[str, str],
    ) -> None:
        async with AsyncUnixDatagramClient(
            remote_address,
            datagram_protocol,
            "asyncio",
            local_path=local_path,
        ) as client:
            assert client.is_connected()
            assert client.get_local_name().as_pathname() == pathlib.Path(local_path)

            async with asyncio.timeout(5):
                await client.send_packet("Test")
                assert await client.recv_packet() == "Test"

    async def test____dunder_init____peer_name____not_set(
        self,
        unix_datagram_socket_factory: Callable[[], Socket],
        datagram_protocol: DatagramProtocol[str, str],
    ) -> None:
        with pytest.raises(OSError):
            _ = AsyncUnixDatagramClient(unix_datagram_socket_factory(), datagram_protocol, "asyncio")

    async def test____dunder_init____local_name____not_set(
        self,
        remote_address: str | bytes,
        unix_datagram_socket_factory: Callable[[], Socket],
        datagram_protocol: DatagramProtocol[str, str],
    ) -> None:
        unix_datagram_socket_factory = inspect.unwrap(unix_datagram_socket_factory)
        sock = unix_datagram_socket_factory()
        sock.connect(remote_address)
        assert not sock.getsockname()
        with pytest.raises(ValueError, match=r"^AsyncUnixDatagramClient requires the socket to be named.$"):
            _ = AsyncUnixDatagramClient(sock, datagram_protocol, "asyncio")

    async def test____wait_connected____idempotent(
        self,
        local_path: str,
        remote_address: str | bytes,
        datagram_protocol: DatagramProtocol[str, str],
    ) -> None:
        async with contextlib.aclosing(
            AsyncUnixDatagramClient(
                remote_address,
                datagram_protocol,
                "asyncio",
                local_path=local_path,
            )
        ) as client:
            await client.wait_connected()
            assert client.is_connected()
            await client.wait_connected()
            assert client.is_connected()

    async def test____wait_connected____simultaneous(
        self,
        local_path: str,
        remote_address: str | bytes,
        datagram_protocol: DatagramProtocol[str, str],
    ) -> None:
        async with contextlib.aclosing(
            AsyncUnixDatagramClient(
                remote_address,
                datagram_protocol,
                "asyncio",
                local_path=local_path,
            )
        ) as client:
            await asyncio.gather(*[client.wait_connected() for _ in range(5)])
            assert client.is_connected()

    async def test____wait_connected____is_closing____connection_not_performed_yet(
        self,
        local_path: str,
        remote_address: str | bytes,
        datagram_protocol: DatagramProtocol[str, str],
    ) -> None:
        async with contextlib.aclosing(
            AsyncUnixDatagramClient(
                remote_address,
                datagram_protocol,
                "asyncio",
                local_path=local_path,
            )
        ) as client:
            assert not client.is_connected()
            assert not client.is_closing()
            await client.wait_connected()
            assert client.is_connected()
            assert not client.is_closing()

    async def test____wait_connected____close_before_trying_to_connect(
        self,
        local_path: str,
        remote_address: str | bytes,
        datagram_protocol: DatagramProtocol[str, str],
    ) -> None:
        client = AsyncUnixDatagramClient(
            remote_address,
            datagram_protocol,
            "asyncio",
            local_path=local_path,
        )
        await client.aclose()
        with pytest.raises(ClientClosedError):
            await client.wait_connected()

    async def test____socket_property____connection_not_performed_yet(
        self,
        local_path: str,
        remote_address: str | bytes,
        datagram_protocol: DatagramProtocol[str, str],
    ) -> None:
        async with contextlib.aclosing(
            AsyncUnixDatagramClient(
                remote_address,
                datagram_protocol,
                "asyncio",
                local_path=local_path,
            )
        ) as client:
            with pytest.raises(AttributeError):
                _ = client.socket

            await client.wait_connected()

            assert isinstance(client.socket, SocketProxy)
            assert client.socket is client.socket

    async def test____get_local_name____connection_not_performed_yet(
        self,
        local_path: str,
        remote_address: str | bytes,
        datagram_protocol: DatagramProtocol[str, str],
    ) -> None:
        async with contextlib.aclosing(
            AsyncUnixDatagramClient(
                remote_address,
                datagram_protocol,
                "asyncio",
                local_path=local_path,
            )
        ) as client:
            with pytest.raises(OSError):
                _ = client.get_local_name()

            await client.wait_connected()

            assert client.get_local_name().as_raw() == local_path

    async def test____get_peer_name____connection_not_performed_yet(
        self,
        local_path: str,
        remote_address: str | bytes,
        datagram_protocol: DatagramProtocol[str, str],
    ) -> None:
        async with contextlib.aclosing(
            AsyncUnixDatagramClient(
                remote_address,
                datagram_protocol,
                "asyncio",
                local_path=local_path,
            )
        ) as client:
            with pytest.raises(OSError):
                _ = client.get_peer_name()

            await client.wait_connected()

            assert client.get_peer_name().as_raw() == remote_address

    async def test____send_packet____recv_packet____implicit_connection(
        self,
        local_path: str,
        remote_address: str | bytes,
        datagram_protocol: DatagramProtocol[str, str],
    ) -> None:
        async with contextlib.aclosing(
            AsyncUnixDatagramClient(
                remote_address,
                datagram_protocol,
                "asyncio",
                local_path=local_path,
            )
        ) as client:
            assert not client.is_connected()

            async with asyncio.timeout(3):
                await client.send_packet("Connected")
                assert await client.recv_packet() == "Connected"

            assert client.is_connected()
