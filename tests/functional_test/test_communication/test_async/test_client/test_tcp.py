from __future__ import annotations

import asyncio
import contextlib
import ssl
from collections.abc import AsyncIterator
from socket import AF_INET, IPPROTO_TCP, SHUT_WR, TCP_NODELAY, socket as Socket

from easynetwork.clients.async_tcp import AsyncTCPNetworkClient
from easynetwork.exceptions import ClientClosedError, StreamProtocolParseError
from easynetwork.lowlevel.socket import IPv4SocketAddress, IPv6SocketAddress, SocketProxy
from easynetwork.lowlevel.std_asyncio.backend import AsyncIOBackend
from easynetwork.protocol import StreamProtocol

import pytest
import pytest_asyncio


async def readline(loop: asyncio.AbstractEventLoop, sock: Socket) -> bytes:
    buf: list[bytes] = []
    while True:
        chunk = await loop.sock_recv(sock, 1024)
        if not chunk:
            break
        buf.append(chunk)
        if b"\n" in chunk:
            break
    return b"".join(buf)


@pytest.mark.asyncio
@pytest.mark.usefixtures("simulate_no_ssl_module")
@pytest.mark.flaky(retries=3, delay=1)
class TestAsyncTCPNetworkClient:
    @pytest.fixture
    @staticmethod
    def server(socket_pair: tuple[Socket, Socket]) -> Socket:
        server = socket_pair[0]
        server.setsockopt(IPPROTO_TCP, TCP_NODELAY, 1)
        server.setblocking(False)
        return server

    @pytest.fixture
    @staticmethod
    def asyncio_backend() -> AsyncIOBackend:
        return AsyncIOBackend()

    @pytest_asyncio.fixture
    @staticmethod
    async def client(
        asyncio_backend: AsyncIOBackend,
        socket_pair: tuple[Socket, Socket],
        stream_protocol: StreamProtocol[str, str],
    ) -> AsyncIterator[AsyncTCPNetworkClient[str, str]]:
        async with AsyncTCPNetworkClient(socket_pair[1], stream_protocol, asyncio_backend) as client:
            assert client.is_connected()
            yield client

    @pytest.fixture
    @staticmethod
    def is_buffered_protocol(stream_protocol: StreamProtocol[str, str]) -> bool:
        try:
            stream_protocol.buffered_receiver()
        except NotImplementedError:
            return False
        return True

    async def test____aclose____idempotent(self, client: AsyncTCPNetworkClient[str, str]) -> None:
        assert not client.is_closing()
        await client.aclose()
        assert client.is_closing()
        await client.aclose()
        assert client.is_closing()

    async def test____send_packet____default(
        self,
        client: AsyncTCPNetworkClient[str, str],
        server: Socket,
    ) -> None:
        event_loop = asyncio.get_running_loop()

        await client.send_packet("ABCDEF")
        assert await readline(event_loop, server) == b"ABCDEF\n"

    async def test____send_packet____closed_client(self, client: AsyncTCPNetworkClient[str, str]) -> None:
        await client.aclose()
        with pytest.raises(ClientClosedError):
            await client.send_packet("ABCDEF")

    @pytest.mark.parametrize("incremental_serializer", [pytest.param("bad_serialize", id="serializer_crash")], indirect=True)
    async def test____send_packet____protocol_crashed(
        self,
        client: AsyncTCPNetworkClient[str, str],
    ) -> None:
        with pytest.raises(RuntimeError, match=r"^protocol\.generate_chunks\(\) crashed$"):
            await client.send_packet("ABCDEF")

    async def test____send_eof____close_write_stream(
        self,
        client: AsyncTCPNetworkClient[str, str],
        server: Socket,
    ) -> None:
        event_loop = asyncio.get_running_loop()

        await client.send_eof()
        assert await readline(event_loop, server) == b""
        with pytest.raises(RuntimeError):
            await client.send_packet("ABC")
        await event_loop.sock_sendall(server, b"ABCDEF\n")
        assert await client.recv_packet() == "ABCDEF"

    async def test____send_eof____closed_client(
        self,
        client: AsyncTCPNetworkClient[str, str],
    ) -> None:
        await client.aclose()
        await client.send_eof()

    async def test____send_eof____idempotent(
        self,
        client: AsyncTCPNetworkClient[str, str],
        server: Socket,
    ) -> None:
        event_loop = asyncio.get_running_loop()

        await client.send_eof()
        assert await readline(event_loop, server) == b""
        await client.send_eof()
        await client.send_eof()

    async def test____recv_packet____default(
        self,
        client: AsyncTCPNetworkClient[str, str],
        server: Socket,
    ) -> None:
        event_loop = asyncio.get_running_loop()

        await event_loop.sock_sendall(server, b"ABCDEF\n")
        assert await client.recv_packet() == "ABCDEF"

    async def test____recv_packet____partial(
        self,
        client: AsyncTCPNetworkClient[str, str],
        server: Socket,
    ) -> None:
        event_loop = asyncio.get_running_loop()

        await event_loop.sock_sendall(server, b"ABC")
        event_loop.call_later(0.5, server.sendall, b"DEF\n")
        assert await client.recv_packet() == "ABCDEF"

    async def test____recv_packet____buffer(
        self,
        client: AsyncTCPNetworkClient[str, str],
        server: Socket,
    ) -> None:
        event_loop = asyncio.get_running_loop()

        await event_loop.sock_sendall(server, b"A\nB\nC\nD\n")
        assert await client.recv_packet() == "A"
        assert await client.recv_packet() == "B"
        assert await client.recv_packet() == "C"
        assert await client.recv_packet() == "D"
        await event_loop.sock_sendall(server, b"E\nF\nG\nH\nI")
        assert await client.recv_packet() == "E"
        assert await client.recv_packet() == "F"
        assert await client.recv_packet() == "G"
        assert await client.recv_packet() == "H"

        task = asyncio.create_task(client.recv_packet())
        await asyncio.sleep(0)
        assert not task.done()
        await event_loop.sock_sendall(server, b"J\n")
        assert await task == "IJ"

    async def test____recv_packet____eof____closed_remote(self, client: AsyncTCPNetworkClient[str, str], server: Socket) -> None:
        server.close()
        with pytest.raises(ConnectionAbortedError):
            await client.recv_packet()

    async def test____recv_packet____eof____shutdown_write_only(
        self,
        client: AsyncTCPNetworkClient[str, str],
        server: Socket,
    ) -> None:
        event_loop = asyncio.get_running_loop()

        server.shutdown(SHUT_WR)
        with pytest.raises(ConnectionAbortedError):
            await client.recv_packet()

        await client.send_packet("ABCDEF")
        assert await readline(event_loop, server) == b"ABCDEF\n"

    async def test____recv_packet____client_close_error(self, client: AsyncTCPNetworkClient[str, str]) -> None:
        await client.aclose()
        with pytest.raises(ClientClosedError):
            await client.recv_packet()

    async def test____recv_packet____invalid_data(
        self,
        client: AsyncTCPNetworkClient[str, str],
        server: Socket,
    ) -> None:
        event_loop = asyncio.get_running_loop()

        await event_loop.sock_sendall(server, "\u00E9\nvalid\n".encode("latin-1"))
        with pytest.raises(StreamProtocolParseError):
            await client.recv_packet()
        assert await client.recv_packet() == "valid"

    @pytest.mark.parametrize(
        "incremental_serializer",
        [
            pytest.param("invalid", id="serializer_crash"),
            pytest.param("invalid_buffered", id="buffered_serializer_crash"),
        ],
        indirect=True,
    )
    async def test____recv_packet____protocol_crashed(
        self,
        is_buffered_protocol: bool,
        client: AsyncTCPNetworkClient[str, str],
        server: Socket,
    ) -> None:
        event_loop = asyncio.get_running_loop()

        expected_pattern: str
        if is_buffered_protocol:
            pytest.xfail("asyncio implementation does not support buffered serializer yet.")
            # expected_pattern = r"^protocol\.build_packet_from_buffer\(\) crashed$"
        else:
            expected_pattern = r"^protocol\.build_packet_from_chunks\(\) crashed$"
        await event_loop.sock_sendall(server, b"ABCDEF\n")
        with pytest.raises(RuntimeError, match=expected_pattern):
            await client.recv_packet()

    async def test____iter_received_packets____yields_available_packets_until_eof(
        self,
        client: AsyncTCPNetworkClient[str, str],
        server: Socket,
    ) -> None:
        event_loop = asyncio.get_running_loop()

        await event_loop.sock_sendall(server, b"A\nB\nC\nD\nE\nF")
        event_loop.call_soon(server.shutdown, SHUT_WR)
        event_loop.call_soon(server.close)
        assert [p async for p in client.iter_received_packets(timeout=None)] == ["A", "B", "C", "D", "E"]

    async def test____iter_received_packets____yields_available_packets_within_timeout(
        self,
        client: AsyncTCPNetworkClient[str, str],
        server: Socket,
    ) -> None:
        event_loop = asyncio.get_running_loop()

        async def send_coro() -> None:
            await event_loop.sock_sendall(server, b"A\n")
            await asyncio.sleep(0.1)
            await event_loop.sock_sendall(server, b"B\n")
            await asyncio.sleep(0.4)
            await event_loop.sock_sendall(server, b"C\n")
            await asyncio.sleep(0.2)
            await event_loop.sock_sendall(server, b"D\n")
            await asyncio.sleep(0.5)
            await event_loop.sock_sendall(server, b"E\n")

        send_task = asyncio.create_task(send_coro())
        try:
            assert [p async for p in client.iter_received_packets(timeout=1)] == ["A", "B", "C", "D"]
        finally:
            send_task.cancel()
            await asyncio.wait({send_task})

    async def test____get_local_address____consistency(self, socket_family: int, client: AsyncTCPNetworkClient[str, str]) -> None:
        address = client.get_local_address()
        if socket_family == AF_INET:
            assert isinstance(address, IPv4SocketAddress)
        else:
            assert isinstance(address, IPv6SocketAddress)
        assert address == client.socket.getsockname()

    async def test____get_remote_address____consistency(
        self,
        socket_family: int,
        client: AsyncTCPNetworkClient[str, str],
    ) -> None:
        address = client.get_remote_address()
        if socket_family == AF_INET:
            assert isinstance(address, IPv4SocketAddress)
        else:
            assert isinstance(address, IPv6SocketAddress)
        assert address == client.socket.getpeername()


@pytest.mark.asyncio
@pytest.mark.usefixtures("simulate_no_ssl_module")
class TestAsyncTCPNetworkClientConnection:
    @pytest_asyncio.fixture(autouse=True)
    @staticmethod
    async def server(localhost_ip: str, socket_family: int) -> AsyncIterator[asyncio.Server]:
        async def client_connected_cb(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                data: bytes = await reader.readline()
                writer.write(data)
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        async with await asyncio.start_server(
            client_connected_cb,
            host=localhost_ip,
            port=0,
            family=socket_family,
        ) as server:
            await asyncio.sleep(0.01)
            yield server

    @pytest.fixture
    @staticmethod
    def remote_address(server: asyncio.Server) -> tuple[str, int]:
        return server.sockets[0].getsockname()[:2]

    @pytest.fixture
    @staticmethod
    def asyncio_backend() -> AsyncIOBackend:
        return AsyncIOBackend()

    async def test____dunder_init____connect_to_server(
        self,
        asyncio_backend: AsyncIOBackend,
        remote_address: tuple[str, int],
        stream_protocol: StreamProtocol[str, str],
    ) -> None:
        async with AsyncTCPNetworkClient(remote_address, stream_protocol, asyncio_backend) as client:
            assert client.is_connected()
            await client.send_packet("Test")
            assert await client.recv_packet() == "Test"

    async def test____dunder_init____with_local_address(
        self,
        localhost_ip: str,
        remote_address: tuple[str, int],
        stream_protocol: StreamProtocol[str, str],
        asyncio_backend: AsyncIOBackend,
    ) -> None:
        async with AsyncTCPNetworkClient(
            remote_address,
            stream_protocol,
            asyncio_backend,
            local_address=(localhost_ip, 0),
        ) as client:
            await client.send_packet("Test")
            assert await client.recv_packet() == "Test"

    async def test____wait_connected____idempotent(
        self,
        remote_address: tuple[str, int],
        stream_protocol: StreamProtocol[str, str],
        asyncio_backend: AsyncIOBackend,
    ) -> None:
        async with contextlib.aclosing(
            AsyncTCPNetworkClient(remote_address, stream_protocol, asyncio_backend),
        ) as client:
            assert not client.is_connected()
            await client.wait_connected()
            assert client.is_connected()
            await client.wait_connected()
            assert client.is_connected()

    async def test____wait_connected____simultaneous(
        self,
        remote_address: tuple[str, int],
        stream_protocol: StreamProtocol[str, str],
        asyncio_backend: AsyncIOBackend,
    ) -> None:
        async with contextlib.aclosing(AsyncTCPNetworkClient(remote_address, stream_protocol, asyncio_backend)) as client:
            await asyncio.gather(*[client.wait_connected() for _ in range(5)])
            assert client.is_connected()

    async def test____wait_connected____is_closing____connection_not_performed_yet(
        self,
        remote_address: tuple[str, int],
        stream_protocol: StreamProtocol[str, str],
        asyncio_backend: AsyncIOBackend,
    ) -> None:
        async with contextlib.aclosing(AsyncTCPNetworkClient(remote_address, stream_protocol, asyncio_backend)) as client:
            assert not client.is_connected()
            assert not client.is_closing()
            await client.wait_connected()
            assert client.is_connected()
            assert not client.is_closing()

    async def test____wait_connected____close_before_trying_to_connect(
        self,
        remote_address: tuple[str, int],
        stream_protocol: StreamProtocol[str, str],
        asyncio_backend: AsyncIOBackend,
    ) -> None:
        async with contextlib.aclosing(AsyncTCPNetworkClient(remote_address, stream_protocol, asyncio_backend)) as client:
            await client.aclose()
            with pytest.raises(ClientClosedError):
                await client.wait_connected()

    async def test____socket_property____connection_not_performed_yet(
        self,
        remote_address: tuple[str, int],
        stream_protocol: StreamProtocol[str, str],
        asyncio_backend: AsyncIOBackend,
    ) -> None:
        async with contextlib.aclosing(AsyncTCPNetworkClient(remote_address, stream_protocol, asyncio_backend)) as client:
            with pytest.raises(AttributeError):
                _ = client.socket

            await client.wait_connected()

            assert isinstance(client.socket, SocketProxy)

    async def test____get_local_address____connection_not_performed_yet(
        self,
        remote_address: tuple[str, int],
        stream_protocol: StreamProtocol[str, str],
        asyncio_backend: AsyncIOBackend,
    ) -> None:
        async with contextlib.aclosing(AsyncTCPNetworkClient(remote_address, stream_protocol, asyncio_backend)) as client:
            with pytest.raises(OSError):
                _ = client.get_local_address()

            await client.wait_connected()

            assert client.get_local_address()

    async def test____get_remote_address____connection_not_performed_yet(
        self,
        remote_address: tuple[str, int],
        stream_protocol: StreamProtocol[str, str],
        asyncio_backend: AsyncIOBackend,
    ) -> None:
        async with contextlib.aclosing(AsyncTCPNetworkClient(remote_address, stream_protocol, asyncio_backend)) as client:
            with pytest.raises(OSError):
                _ = client.get_remote_address()

            await client.wait_connected()

            assert client.get_remote_address()[:2] == remote_address

    async def test____send_packet____recv_packet____implicit_connection(
        self,
        remote_address: tuple[str, int],
        stream_protocol: StreamProtocol[str, str],
        asyncio_backend: AsyncIOBackend,
    ) -> None:
        async with contextlib.aclosing(AsyncTCPNetworkClient(remote_address, stream_protocol, asyncio_backend)) as client:
            assert not client.is_connected()

            await client.send_packet("Connected")
            assert await client.recv_packet() == "Connected"

            assert client.is_connected()


@pytest.mark.asyncio
class TestAsyncSSLOverTCPNetworkClient:
    @pytest_asyncio.fixture(autouse=True)
    @staticmethod
    async def server(localhost_ip: str, socket_family: int, server_ssl_context: ssl.SSLContext) -> AsyncIterator[asyncio.Server]:
        async def client_connected_cb(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                data: bytes = await reader.readline()
                writer.write(data)
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        async with await asyncio.start_server(
            client_connected_cb,
            host=localhost_ip,
            port=0,
            family=socket_family,
            ssl=server_ssl_context,
        ) as server:
            await asyncio.sleep(0.01)
            yield server

    @pytest.fixture
    @staticmethod
    def remote_address(server: asyncio.Server) -> tuple[str, int]:
        return server.sockets[0].getsockname()[:2]

    @pytest.fixture
    @staticmethod
    def asyncio_backend() -> AsyncIOBackend:
        return AsyncIOBackend()

    async def test____dunder_init____handshake_and_shutdown(
        self,
        remote_address: tuple[str, int],
        stream_protocol: StreamProtocol[str, str],
        asyncio_backend: AsyncIOBackend,
        client_ssl_context: ssl.SSLContext,
    ) -> None:
        # Arrange

        # Act & Assert
        async with AsyncTCPNetworkClient(
            remote_address,
            stream_protocol,
            asyncio_backend,
            ssl=client_ssl_context,
            server_hostname="test.example.com",
        ) as client:
            await client.send_packet("Test")
            assert await client.recv_packet() == "Test"

    async def test____dunder_init____use_default_context(
        self,
        remote_address: tuple[str, int],
        stream_protocol: StreamProtocol[str, str],
        client_ssl_context: ssl.SSLContext,
        asyncio_backend: AsyncIOBackend,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Arrange
        monkeypatch.setattr(ssl, "create_default_context", lambda *args, **kwargs: client_ssl_context)

        # Act & Assert
        async with AsyncTCPNetworkClient(
            remote_address,
            stream_protocol,
            asyncio_backend,
            ssl=True,
            server_hostname="test.example.com",
        ) as client:
            await client.send_packet("Test")
            assert await client.recv_packet() == "Test"

    async def test____dunder_init____use_default_context____disable_hostname_check(
        self,
        remote_address: tuple[str, int],
        stream_protocol: StreamProtocol[str, str],
        client_ssl_context: ssl.SSLContext,
        asyncio_backend: AsyncIOBackend,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Arrange
        check_hostname_by_default: bool = client_ssl_context.check_hostname
        assert check_hostname_by_default
        monkeypatch.setattr(ssl, "create_default_context", lambda *args, **kwargs: client_ssl_context)

        # Act & Assert
        async with AsyncTCPNetworkClient(
            remote_address,
            stream_protocol,
            asyncio_backend,
            ssl=True,
            server_hostname="",
        ) as client:
            assert not client_ssl_context.check_hostname  # It must be set to False if server_hostname is an empty string
            await client.send_packet("Test")
            assert await client.recv_packet() == "Test"

    @pytest.mark.usefixtures("simulate_no_ssl_module")
    async def test____dunder_init____no_ssl_module_available(
        self,
        remote_address: tuple[str, int],
        stream_protocol: StreamProtocol[str, str],
        asyncio_backend: AsyncIOBackend,
        client_ssl_context: ssl.SSLContext,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(RuntimeError, match=r"^stdlib ssl module not available$"):
            _ = AsyncTCPNetworkClient(
                remote_address,
                stream_protocol,
                asyncio_backend,
                ssl=client_ssl_context,
                server_hostname="test.example.com",
            )

    async def test____send_eof____not_supported(
        self,
        remote_address: tuple[str, int],
        stream_protocol: StreamProtocol[str, str],
        asyncio_backend: AsyncIOBackend,
        client_ssl_context: ssl.SSLContext,
    ) -> None:
        # Arrange

        # Act & Assert
        async with AsyncTCPNetworkClient(
            remote_address,
            stream_protocol,
            asyncio_backend,
            ssl=client_ssl_context,
            server_hostname="test.example.com",
        ) as client:
            with pytest.raises(NotImplementedError):
                await client.send_eof()

            await client.send_packet("Test")
            assert await client.recv_packet() == "Test"
