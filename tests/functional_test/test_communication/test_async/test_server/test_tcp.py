# -*- coding: Utf-8 -*-

from __future__ import annotations

import asyncio
import collections
import contextlib
import logging
from socket import IPPROTO_TCP, TCP_NODELAY, socket as Socket
from typing import Any, AsyncIterator, Awaitable, Callable
from weakref import WeakValueDictionary

from easynetwork.api_async.backend.abc import AbstractAsyncBackend
from easynetwork.api_async.server.handler import AsyncClientInterface, AsyncStreamRequestHandler
from easynetwork.api_async.server.tcp import AsyncTCPNetworkServer
from easynetwork.exceptions import BaseProtocolParseError, ClientClosedError, StreamProtocolParseError
from easynetwork.protocol import StreamProtocol
from easynetwork.tools.socket import SocketAddress

import pytest
import pytest_asyncio

from .base import BaseTestAsyncServer


class RandomErrorWithLogs(Exception):
    pass


class RandomError(Exception):
    pass


class MyAsyncTCPRequestHandler(AsyncStreamRequestHandler[str, str]):
    connected_clients: WeakValueDictionary[SocketAddress, AsyncClientInterface[str]]
    request_received: collections.defaultdict[tuple[Any, ...], list[str]]
    bad_request_received: collections.defaultdict[tuple[Any, ...], list[BaseProtocolParseError]]
    backend: AbstractAsyncBackend
    service_actions_count: int
    close_all_clients_on_service_actions: bool = False

    async def service_init(self, backend: AbstractAsyncBackend) -> None:
        await super().service_init(backend)
        self.backend = backend
        self.connected_clients = WeakValueDictionary()
        self.service_actions_count = 0
        self.request_received = collections.defaultdict(list)
        self.bad_request_received = collections.defaultdict(list)

    async def service_actions(self) -> None:
        await super().service_actions()
        self.service_actions_count += 1
        if self.close_all_clients_on_service_actions:
            for client in list(self.connected_clients.values()):
                await client.aclose()

    async def service_quit(self) -> None:
        del self.connected_clients, self.backend, self.service_actions_count, self.request_received, self.bad_request_received
        await super().service_quit()

    async def on_connection(self, client: AsyncClientInterface[str]) -> None:
        await super().on_connection(client)
        assert client.address not in self.connected_clients
        self.connected_clients[client.address] = client
        await client.send_packet("milk")

    async def on_disconnection(self, client: AsyncClientInterface[str]) -> None:
        del self.connected_clients[client.address]
        await super().on_disconnection(client)

    async def handle(self, request: str, client: AsyncClientInterface[str]) -> None:
        match request:
            case "__error_with_logs__":
                raise RandomErrorWithLogs("Sorry man!")
            case "__error__":
                raise RandomError("Sorry man!")
            case "__close__":
                await client.aclose()
            case "__os_error__":
                raise OSError("Server issue.")
            case _:
                self.request_received[client.address].append(request)
                await client.send_packet(request.upper())

    async def handle_error(self, client: AsyncClientInterface[str], exc: Exception) -> bool:
        if isinstance(exc, OSError):
            assert client.is_closing()
            with pytest.raises(ClientClosedError):
                await client.send_packet(f'{exc.__class__.__name__}("{exc}")')
            return False

        assert not client.is_closing()
        await client.send_packet(f'{exc.__class__.__name__}("{exc}")')
        match exc:
            case RandomErrorWithLogs():
                return await super().handle_error(client, exc)
            case _:
                return True

    async def bad_request(self, client: AsyncClientInterface[str], exc: BaseProtocolParseError) -> None:
        await super().bad_request(client, exc)
        self.bad_request_received[client.address].append(exc)
        await client.send_packet("wrong encoding man.")


class MyAsyncTCPServer(AsyncTCPNetworkServer[str, str]):
    __slots__ = ()


@pytest.mark.asyncio
class TestAsyncTCPNetworkServer(BaseTestAsyncServer):
    @pytest.fixture
    @staticmethod
    def backend_kwargs(use_asyncio_transport: bool) -> dict[str, Any]:
        return {"transport": use_asyncio_transport}

    @pytest.fixture
    @staticmethod
    def request_handler() -> MyAsyncTCPRequestHandler:
        return MyAsyncTCPRequestHandler()

    @pytest_asyncio.fixture
    @staticmethod
    async def server(
        request_handler: MyAsyncTCPRequestHandler,
        socket_family: int,
        localhost: str,
        unused_tcp_port: int,
        stream_protocol: StreamProtocol[str, str],
        backend_kwargs: dict[str, Any],
    ) -> AsyncIterator[MyAsyncTCPServer]:
        async with MyAsyncTCPServer(
            localhost,
            unused_tcp_port,
            stream_protocol,
            request_handler,
            family=socket_family,
            backend_kwargs=backend_kwargs,
        ) as server:
            assert not server.sockets
            yield server

    @pytest_asyncio.fixture
    @staticmethod
    async def server_address(run_server: None, server: MyAsyncTCPServer) -> tuple[str, int]:
        async with asyncio.timeout(1):
            await server.wait_for_server_to_be_up()
        assert server.is_serving()
        return server.sockets[0].getsockname()[:2]

    @pytest.fixture
    @staticmethod
    def run_server_and_wait(run_server: None, server_address: Any) -> None:
        pass

    @pytest_asyncio.fixture
    @staticmethod
    async def client_factory(
        server_address: tuple[str, int],
        tcp_socket_factory: Callable[[], Socket],
        event_loop: asyncio.AbstractEventLoop,
    ) -> AsyncIterator[Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]]]:
        async with contextlib.AsyncExitStack() as stack:

            async def factory() -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
                sock = tcp_socket_factory()
                sock.setblocking(False)
                await event_loop.sock_connect(sock, server_address)
                reader, writer = await asyncio.open_connection(sock=sock)
                stack.push_async_callback(writer.wait_closed)
                stack.callback(writer.close)
                assert await reader.readline() == b"milk\n"
                return reader, writer

            yield factory

    @pytest.mark.parametrize("host", [None, ""], ids=repr)
    async def test____dunder_init____bind_on_all_available_interfaces(
        self,
        host: str | None,
        unused_tcp_port: int,
        request_handler: MyAsyncTCPRequestHandler,
        stream_protocol: StreamProtocol[str, str],
        backend_kwargs: dict[str, Any],
    ) -> None:
        async with MyAsyncTCPServer(host, unused_tcp_port, stream_protocol, request_handler, backend_kwargs=backend_kwargs) as s:
            _ = asyncio.create_task(s.serve_forever())
            async with asyncio.timeout(1):
                await s.wait_for_server_to_be_up()

            assert len(s.sockets) > 0

            await s.shutdown()

    @pytest.mark.usefixtures("run_server_and_wait")
    async def test____serve_forever____backend_assignment(
        self,
        server: MyAsyncTCPServer,
        request_handler: MyAsyncTCPRequestHandler,
    ) -> None:
        assert request_handler.backend is server.get_backend()

    async def test____serve_forever____accept_client(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        request_handler: MyAsyncTCPRequestHandler,
    ) -> None:
        reader, writer = await client_factory()
        client_address: tuple[Any, ...] = writer.get_extra_info("sockname")

        assert client_address in request_handler.connected_clients

        writer.write(b"hello, world.\n")
        await writer.drain()
        assert await reader.readline() == b"HELLO, WORLD.\n"

        assert request_handler.request_received[client_address] == ["hello, world."]

        writer.close()
        await writer.wait_closed()

        async with asyncio.timeout(1):
            while client_address in request_handler.connected_clients:
                await asyncio.sleep(0.1)

    @pytest.mark.usefixtures("run_server_and_wait")
    async def test____serve_forever_____service_actions(self, request_handler: MyAsyncTCPRequestHandler) -> None:
        await asyncio.sleep(0.2)
        assert request_handler.service_actions_count >= 1

    async def test____serve_forever____disable_nagle_algorithm(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        request_handler: MyAsyncTCPRequestHandler,
    ) -> None:
        _ = await client_factory()

        connected_client: AsyncClientInterface[str] = list(request_handler.connected_clients.values())[0]

        tcp_nodelay_state: int = connected_client.socket.getsockopt(IPPROTO_TCP, TCP_NODELAY)

        # Do not test with '== 1', on MacOS it will return 4
        # (c.f. https://stackoverflow.com/a/31835137)
        assert tcp_nodelay_state != 0

    async def test____serve_forever____close_during_loop____continue_until_all_clients_are_gone(
        self,
        server: MyAsyncTCPServer,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
    ) -> None:
        reader, writer = await client_factory()

        await server.server_close()
        await asyncio.sleep(0.3)

        writer.write(b"hello\n")
        await writer.drain()
        assert await reader.readline() == b"HELLO\n"
        writer.write(b"world!\n")
        await writer.drain()
        assert await reader.readline() == b"WORLD!\n"

        writer.close()
        await writer.wait_closed()
        await asyncio.sleep(0.3)

    async def test____serve_forever____partial_request(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        request_handler: MyAsyncTCPRequestHandler,
    ) -> None:
        reader, writer = await client_factory()
        client_address: tuple[Any, ...] = writer.get_extra_info("sockname")

        writer.write(b"hello")
        await writer.drain()
        await asyncio.sleep(0.1)

        writer.write(b", world!\n")
        await writer.drain()

        assert await reader.readline() == b"HELLO, WORLD!\n"
        assert request_handler.request_received[client_address] == ["hello, world!"]

    async def test____serve_forever____several_requests_at_same_time(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        request_handler: MyAsyncTCPRequestHandler,
    ) -> None:
        reader, writer = await client_factory()
        client_address: tuple[Any, ...] = writer.get_extra_info("sockname")

        writer.write(b"hello\nworld\n")
        await writer.drain()
        await asyncio.sleep(0.1)

        assert await reader.readline() == b"HELLO\n"
        assert await reader.readline() == b"WORLD\n"
        assert request_handler.request_received[client_address] == ["hello", "world"]

    async def test____serve_forever____bad_request(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        request_handler: MyAsyncTCPRequestHandler,
    ) -> None:
        reader, writer = await client_factory()
        client_address: tuple[Any, ...] = writer.get_extra_info("sockname")

        writer.write("\u00E9\n".encode("latin-1"))  # StringSerializer does not accept unicode
        await writer.drain()
        await asyncio.sleep(0.1)

        assert await reader.readline() == b"wrong encoding man.\n"
        assert request_handler.request_received[client_address] == []
        assert isinstance(request_handler.bad_request_received[client_address][0], StreamProtocolParseError)
        assert request_handler.bad_request_received[client_address][0].error_type == "deserialization"
        assert request_handler.bad_request_received[client_address][0].__traceback__ is None

    @pytest.mark.parametrize("with_logs", [False, True], ids=lambda boolean: f"with_logs=={boolean}")
    async def test____serve_forever____unexpected_error_during_process(
        self,
        with_logs: bool,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        caplog: pytest.LogCaptureFixture,
        server: MyAsyncTCPServer,
    ) -> None:
        caplog.set_level(logging.ERROR, server.logger.name)
        reader, writer = await client_factory()

        if with_logs:
            writer.write(b"__error_with_logs__\n")
        else:
            writer.write(b"__error__\n")
        await writer.drain()
        await asyncio.sleep(0.1)

        if with_logs:
            assert await reader.readline() == b'RandomErrorWithLogs("Sorry man!")\n'
            assert len(caplog.records) > 0
        else:
            assert await reader.readline() == b'RandomError("Sorry man!")\n'
            assert len(caplog.records) == 0

    async def test____serve_forever____os_error(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
    ) -> None:
        reader, writer = await client_factory()

        writer.write(b"__os_error__\n")
        await writer.drain()
        await asyncio.sleep(0.1)

        assert await reader.read() == b""

    async def test____serve_forever____explicitly_closed_by_request_handler(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
    ) -> None:
        reader, writer = await client_factory()

        writer.write(b"__close__\n")
        await writer.drain()
        await asyncio.sleep(0.1)

        assert await reader.read() == b""

    async def test____serve_forever____explicitly_closed_by_service_actions(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        request_handler: MyAsyncTCPRequestHandler,
    ) -> None:
        reader, _ = await client_factory()

        request_handler.close_all_clients_on_service_actions = True
        await asyncio.sleep(0.2)

        assert await reader.read() == b""
