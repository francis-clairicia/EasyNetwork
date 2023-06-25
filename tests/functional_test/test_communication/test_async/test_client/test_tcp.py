# -*- coding: utf-8 -*-

from __future__ import annotations

import asyncio
import contextlib
import ssl
from socket import AF_INET, IPPROTO_TCP, SHUT_WR, TCP_NODELAY, socket as Socket
from typing import Any, AsyncIterator

from easynetwork.api_async.client.tcp import AsyncTCPNetworkClient
from easynetwork.exceptions import ClientClosedError, StreamProtocolParseError
from easynetwork.protocol import StreamProtocol
from easynetwork.tools.socket import IPv4SocketAddress, IPv6SocketAddress, SocketProxy

import pytest
import pytest_asyncio


@pytest.mark.asyncio
@pytest.mark.usefixtures("simulate_no_ssl_module")
class TestAsyncTCPNetworkClient:
    @pytest.fixture
    @staticmethod
    def server(socket_pair: tuple[Socket, Socket]) -> Socket:
        server = socket_pair[0]
        server.setsockopt(IPPROTO_TCP, TCP_NODELAY, 1)
        server.setblocking(False)
        return server

    @pytest_asyncio.fixture
    @staticmethod
    async def client(
        socket_pair: tuple[Socket, Socket],
        stream_protocol: StreamProtocol[str, str],
        use_asyncio_transport: bool,
    ) -> AsyncIterator[AsyncTCPNetworkClient[str, str]]:
        async with AsyncTCPNetworkClient(
            socket_pair[1],
            stream_protocol,
            backend_kwargs={"transport": use_asyncio_transport},
        ) as client:
            assert client.is_connected()
            yield client

    async def test____aclose____idempotent(self, client: AsyncTCPNetworkClient[str, str]) -> None:
        assert not client.is_closing()
        await client.aclose()
        assert client.is_closing()
        await client.aclose()
        assert client.is_closing()

    async def test____send_packet____default(
        self,
        event_loop: asyncio.AbstractEventLoop,
        client: AsyncTCPNetworkClient[str, str],
        server: Socket,
    ) -> None:
        await client.send_packet("ABCDEF")
        assert await event_loop.sock_recv(server, 1024) == b"ABCDEF\n"

    @pytest.mark.skipif_uvloop  # Error not triggered
    @pytest.mark.platform_linux  # Windows and MacOS raise ConnectionAbortedError but in the 2nd send() call
    async def test____send_packet____connection_error____fresh_connection_closed_by_server(
        self,
        client: AsyncTCPNetworkClient[str, str],
        server: Socket,
    ) -> None:
        server.close()
        with pytest.raises(ConnectionAbortedError):
            await client.send_packet("ABCDEF")

    @pytest.mark.skipif_uvloop  # Error not triggered
    @pytest.mark.platform_linux  # Windows and MacOS raise ConnectionAbortedError but in the 2nd send() call
    async def test____send_packet____connection_error____after_previous_successful_try(
        self,
        event_loop: asyncio.AbstractEventLoop,
        client: AsyncTCPNetworkClient[str, str],
        server: Socket,
    ) -> None:
        await client.send_packet("ABCDEF")
        assert await event_loop.sock_recv(server, 1024) == b"ABCDEF\n"
        server.close()
        with pytest.raises(ConnectionAbortedError):
            await client.send_packet("ABCDEF")

    @pytest.mark.skipif_uvloop  # Error not triggered
    @pytest.mark.platform_linux  # Windows and MacOS raise ConnectionResetError but in the 2nd send() call sometimes (it is random)
    async def test____send_packet____connection_error____partial_read_then_close(
        self,
        event_loop: asyncio.AbstractEventLoop,
        client: AsyncTCPNetworkClient[str, str],
        server: Socket,
    ) -> None:
        await client.send_packet("ABC")
        assert await event_loop.sock_recv(server, 1) == b"A"
        server.close()
        with pytest.raises(ConnectionAbortedError):
            await client.send_packet("DEF")

    async def test____send_packet____closed_client(self, client: AsyncTCPNetworkClient[str, str]) -> None:
        await client.aclose()
        with pytest.raises(ClientClosedError):
            await client.send_packet("ABCDEF")

    async def test____recv_packet____default(
        self,
        event_loop: asyncio.AbstractEventLoop,
        client: AsyncTCPNetworkClient[str, str],
        server: Socket,
    ) -> None:
        await event_loop.sock_sendall(server, b"ABCDEF\n")
        assert await client.recv_packet() == "ABCDEF"

    async def test____recv_packet____partial(
        self,
        event_loop: asyncio.AbstractEventLoop,
        client: AsyncTCPNetworkClient[str, str],
        server: Socket,
    ) -> None:
        await event_loop.sock_sendall(server, b"ABC")
        event_loop.call_later(0.5, server.sendall, b"DEF\n")
        assert await client.recv_packet() == "ABCDEF"

    async def test____recv_packet____buffer(
        self,
        event_loop: asyncio.AbstractEventLoop,
        client: AsyncTCPNetworkClient[str, str],
        server: Socket,
    ) -> None:
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

    async def test____recv_packet____eof(self, client: AsyncTCPNetworkClient[str, str], server: Socket) -> None:
        server.close()
        with pytest.raises(ConnectionAbortedError):
            await client.recv_packet()

    async def test____recv_packet____client_close_error(self, client: AsyncTCPNetworkClient[str, str]) -> None:
        await client.aclose()
        with pytest.raises(ClientClosedError):
            await client.recv_packet()

    async def test____recv_packet____invalid_data(
        self,
        event_loop: asyncio.AbstractEventLoop,
        client: AsyncTCPNetworkClient[str, str],
        server: Socket,
    ) -> None:
        await event_loop.sock_sendall(server, "\u00E9\nvalid\n".encode("latin-1"))
        with pytest.raises(StreamProtocolParseError):
            await client.recv_packet()
        assert await client.recv_packet() == "valid"

    async def test____iter_received_packets____yields_available_packets_until_eof(
        self,
        event_loop: asyncio.AbstractEventLoop,
        client: AsyncTCPNetworkClient[str, str],
        server: Socket,
    ) -> None:
        await event_loop.sock_sendall(server, b"A\nB\nC\nD\nE\nF")
        event_loop.call_soon(server.shutdown, SHUT_WR)
        event_loop.call_soon(server.close)
        assert [p async for p in client.iter_received_packets()] == ["A", "B", "C", "D", "E"]

    async def test____fileno____consistency(self, client: AsyncTCPNetworkClient[str, str]) -> None:
        assert client.fileno() == client.socket.fileno()

    async def test____fileno____closed_client(self, client: AsyncTCPNetworkClient[str, str]) -> None:
        await client.aclose()
        assert client.fileno() == -1

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
    def backend_kwargs(use_asyncio_transport: bool) -> dict[str, Any]:
        return {"transport": use_asyncio_transport}

    async def test____dunder_init____connect_to_server(
        self,
        remote_address: tuple[str, int],
        stream_protocol: StreamProtocol[str, str],
        backend_kwargs: dict[str, Any],
    ) -> None:
        async with AsyncTCPNetworkClient(remote_address, stream_protocol, backend_kwargs=backend_kwargs) as client:
            assert client.is_connected()
            await client.send_packet("Test")
            assert await client.recv_packet() == "Test"

    async def test____dunder_init____with_local_address(
        self,
        localhost_ip: str,
        remote_address: tuple[str, int],
        stream_protocol: StreamProtocol[str, str],
        backend_kwargs: dict[str, Any],
    ) -> None:
        async with AsyncTCPNetworkClient(
            remote_address,
            stream_protocol,
            local_address=(localhost_ip, 0),
            backend_kwargs=backend_kwargs,
        ) as client:
            await client.send_packet("Test")
            assert await client.recv_packet() == "Test"

    async def test____wait_connected____idempotent(
        self,
        remote_address: tuple[str, int],
        stream_protocol: StreamProtocol[str, str],
        backend_kwargs: dict[str, Any],
    ) -> None:
        async with AsyncTCPNetworkClient(remote_address, stream_protocol, backend_kwargs=backend_kwargs) as client:
            await client.wait_connected()
            assert client.is_connected()
            await client.wait_connected()
            assert client.is_connected()

    async def test____wait_connected____simultaneous(
        self,
        remote_address: tuple[str, int],
        stream_protocol: StreamProtocol[str, str],
        backend_kwargs: dict[str, Any],
    ) -> None:
        async with AsyncTCPNetworkClient(remote_address, stream_protocol, backend_kwargs=backend_kwargs) as client:
            async with asyncio.TaskGroup() as task_group:
                _ = task_group.create_task(client.wait_connected())
                _ = task_group.create_task(client.wait_connected())
                await asyncio.sleep(0)
            assert client.is_connected()

    async def test____wait_connected____is_closing____connection_not_performed_yet(
        self,
        remote_address: tuple[str, int],
        stream_protocol: StreamProtocol[str, str],
        backend_kwargs: dict[str, Any],
    ) -> None:
        async with contextlib.aclosing(
            AsyncTCPNetworkClient(
                remote_address,
                stream_protocol,
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
        stream_protocol: StreamProtocol[str, str],
        backend_kwargs: dict[str, Any],
    ) -> None:
        async with contextlib.aclosing(
            AsyncTCPNetworkClient(
                remote_address,
                stream_protocol,
                backend_kwargs=backend_kwargs,
            )
        ) as client:
            await client.aclose()
            with pytest.raises(ClientClosedError):
                await client.wait_connected()

    async def test____socket_property____connection_not_performed_yet(
        self,
        remote_address: tuple[str, int],
        stream_protocol: StreamProtocol[str, str],
        backend_kwargs: dict[str, Any],
    ) -> None:
        async with contextlib.aclosing(
            AsyncTCPNetworkClient(
                remote_address,
                stream_protocol,
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
        stream_protocol: StreamProtocol[str, str],
        backend_kwargs: dict[str, Any],
    ) -> None:
        async with contextlib.aclosing(
            AsyncTCPNetworkClient(
                remote_address,
                stream_protocol,
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
        stream_protocol: StreamProtocol[str, str],
        backend_kwargs: dict[str, Any],
    ) -> None:
        async with contextlib.aclosing(
            AsyncTCPNetworkClient(
                remote_address,
                stream_protocol,
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
        stream_protocol: StreamProtocol[str, str],
        backend_kwargs: dict[str, Any],
    ) -> None:
        async with contextlib.aclosing(
            AsyncTCPNetworkClient(
                remote_address,
                stream_protocol,
                backend_kwargs=backend_kwargs,
            )
        ) as client:
            assert client.fileno() == -1

            await client.wait_connected()

            assert client.fileno() > -1

    async def test____send_packet____recv_packet____implicit_connection(
        self,
        remote_address: tuple[str, int],
        stream_protocol: StreamProtocol[str, str],
        backend_kwargs: dict[str, Any],
    ) -> None:
        async with contextlib.aclosing(
            AsyncTCPNetworkClient(
                remote_address,
                stream_protocol,
                backend_kwargs=backend_kwargs,
            )
        ) as client:
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
    def backend_kwargs() -> dict[str, Any]:
        return {}

    async def test____dunder_init____handshake_and_shutdown(
        self,
        remote_address: tuple[str, int],
        stream_protocol: StreamProtocol[str, str],
        backend_kwargs: dict[str, Any],
        client_ssl_context: ssl.SSLContext,
    ) -> None:
        # Arrange

        # Act & Assert
        async with AsyncTCPNetworkClient(
            remote_address,
            stream_protocol,
            ssl=client_ssl_context,
            server_hostname="test.example.com",
            backend_kwargs=backend_kwargs,
        ) as client:
            await client.send_packet("Test")
            assert await client.recv_packet() == "Test"

    async def test____dunder_init____use_default_context(
        self,
        remote_address: tuple[str, int],
        stream_protocol: StreamProtocol[str, str],
        client_ssl_context: ssl.SSLContext,
        backend_kwargs: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Arrange
        monkeypatch.setattr(ssl, "create_default_context", lambda *args, **kwargs: client_ssl_context)

        # Act & Assert
        async with AsyncTCPNetworkClient(
            remote_address,
            stream_protocol,
            ssl=True,
            server_hostname="test.example.com",
            backend_kwargs=backend_kwargs,
        ) as client:
            await client.send_packet("Test")
            assert await client.recv_packet() == "Test"

    async def test____dunder_init____use_default_context____disable_hostname_check(
        self,
        remote_address: tuple[str, int],
        stream_protocol: StreamProtocol[str, str],
        client_ssl_context: ssl.SSLContext,
        backend_kwargs: dict[str, Any],
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
            ssl=True,
            server_hostname="",
            backend_kwargs=backend_kwargs,
        ) as client:
            assert not client_ssl_context.check_hostname  # It must be set to False if server_hostname is an empty string
            await client.send_packet("Test")
            assert await client.recv_packet() == "Test"

    @pytest.mark.usefixtures("simulate_no_ssl_module")
    async def test____dunder_init____no_ssl_module_available(
        self,
        remote_address: tuple[str, int],
        stream_protocol: StreamProtocol[str, str],
        backend_kwargs: dict[str, Any],
        client_ssl_context: ssl.SSLContext,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(RuntimeError, match=r"^stdlib ssl module not available$"):
            _ = AsyncTCPNetworkClient(
                remote_address,
                stream_protocol,
                ssl=client_ssl_context,
                server_hostname="test.example.com",
                backend_kwargs=backend_kwargs,
            )
