# -*- coding: Utf-8 -*-

from __future__ import annotations

import asyncio
from socket import AF_INET, IPPROTO_TCP, SHUT_WR, TCP_NODELAY, socket as Socket
from typing import AsyncIterator

from easynetwork.api_async.client.tcp import AsyncTCPNetworkClient
from easynetwork.exceptions import ClientClosedError, StreamProtocolParseError
from easynetwork.protocol import StreamProtocol
from easynetwork.tools.socket import IPv4SocketAddress, IPv6SocketAddress

import pytest
import pytest_asyncio


@pytest.mark.asyncio
class TestAsyncTCPNetworkClient:
    @pytest.fixture
    @staticmethod
    def server(socket_pair: tuple[Socket, Socket]) -> Socket:
        server = socket_pair[0]
        server.setsockopt(IPPROTO_TCP, TCP_NODELAY, 1)
        return server

    @pytest_asyncio.fixture
    @staticmethod
    async def client(
        socket_pair: tuple[Socket, Socket],
        stream_protocol: StreamProtocol[str, str],
    ) -> AsyncIterator[AsyncTCPNetworkClient[str, str]]:
        async with await AsyncTCPNetworkClient.from_socket(socket_pair[1], stream_protocol) as client:
            yield client

    async def test____close____double_close(self, client: AsyncTCPNetworkClient[str, str]) -> None:
        assert not client.is_closing()
        await client.close()
        assert client.is_closing()
        await client.close()
        assert client.is_closing()

    async def test____send_packet____default(self, client: AsyncTCPNetworkClient[str, str], server: Socket) -> None:
        await client.send_packet("ABCDEF")
        assert await asyncio.to_thread(server.recv, 1024) == b"ABCDEF\n"

    @pytest.mark.platform_linux  # Windows and macOs raise ConnectionAbortedError but in the 2nd send() call
    async def test____send_packet____connection_error____fresh_connection_closed_by_server(
        self,
        client: AsyncTCPNetworkClient[str, str],
        server: Socket,
    ) -> None:
        server.close()
        with pytest.raises(ConnectionError):
            await client.send_packet("ABCDEF")

    @pytest.mark.platform_linux  # Windows and macOs raise ConnectionAbortedError but in the 2nd send() call
    async def test____send_packet____connection_error____after_previous_successful_try(
        self,
        client: AsyncTCPNetworkClient[str, str],
        server: Socket,
    ) -> None:
        await client.send_packet("ABCDEF")
        assert await asyncio.to_thread(server.recv, 1024) == b"ABCDEF\n"
        server.close()
        with pytest.raises(ConnectionError):
            await client.send_packet("ABCDEF")

    async def test____send_packet____connection_error____partial_read_then_close(
        self,
        client: AsyncTCPNetworkClient[str, str],
        server: Socket,
    ) -> None:
        await client.send_packet("ABC")
        assert await asyncio.to_thread(server.recv, 1) == b"A"
        server.close()
        with pytest.raises(ConnectionError):
            await client.send_packet("DEF")

    async def test____send_packet____closed_client(self, client: AsyncTCPNetworkClient[str, str]) -> None:
        await client.close()
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
        await client.close()
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
        await client.close()
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
