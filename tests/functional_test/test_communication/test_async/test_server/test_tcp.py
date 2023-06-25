# -*- coding: utf-8 -*-

from __future__ import annotations

import asyncio
import collections
import contextlib
import logging
import math
import ssl
from socket import IPPROTO_TCP, TCP_NODELAY
from typing import Any, AsyncGenerator, AsyncIterator, Awaitable, Callable, Sequence
from weakref import WeakValueDictionary

from easynetwork.api_async.backend.abc import AbstractAsyncBackend
from easynetwork.api_async.server.handler import AsyncBaseRequestHandler, AsyncClientInterface, AsyncStreamRequestHandler
from easynetwork.api_async.server.tcp import AsyncTCPNetworkServer
from easynetwork.exceptions import BaseProtocolParseError, ClientClosedError, StreamProtocolParseError
from easynetwork.protocol import StreamProtocol
from easynetwork.tools.socket import SocketAddress
from easynetwork_asyncio._utils import create_connection
from easynetwork_asyncio.backend import AsyncioBackend
from easynetwork_asyncio.stream.listener import ListenerSocketAdapter

import pytest
import pytest_asyncio

from .base import BaseTestAsyncServer


class NoListenerErrorBackend(AsyncioBackend):
    async def create_tcp_listeners(
        self,
        host: str | Sequence[str] | None,
        port: int,
        backlog: int,
        *,
        family: int = 0,
        reuse_port: bool = False,
    ) -> Sequence[ListenerSocketAdapter]:
        return []

    async def create_ssl_over_tcp_listeners(
        self,
        host: str | Sequence[str] | None,
        port: int,
        backlog: int,
        ssl_context: ssl.SSLContext,
        ssl_handshake_timeout: float,
        ssl_shutdown_timeout: float,
        *,
        family: int = 0,
        reuse_port: bool = False,
    ) -> Sequence[ListenerSocketAdapter]:
        return []


class RandomError(Exception):
    pass


class MyAsyncTCPRequestHandler(AsyncStreamRequestHandler[str, str]):
    connected_clients: WeakValueDictionary[SocketAddress, AsyncClientInterface[str]]
    request_received: collections.defaultdict[tuple[Any, ...], list[str]]
    request_count: collections.Counter[tuple[Any, ...]]
    bad_request_received: collections.defaultdict[tuple[Any, ...], list[BaseProtocolParseError]]
    backend: AbstractAsyncBackend
    service_actions_count: int
    close_all_clients_on_service_actions: bool = False
    close_all_clients_on_connection: bool = False
    close_client_after_n_request: int = -1
    crash_service_actions: bool = False
    stop_listening: Callable[[], None]

    def set_async_backend(self, backend: AbstractAsyncBackend) -> None:
        self.backend = backend

    async def service_init(self) -> None:
        await super().service_init()
        self.connected_clients = WeakValueDictionary()
        self.service_actions_count = 0
        self.request_received = collections.defaultdict(list)
        self.request_count = collections.Counter()
        self.bad_request_received = collections.defaultdict(list)

    async def service_actions(self) -> None:
        if self.crash_service_actions:
            raise Exception("CRASH")
        await super().service_actions()
        self.service_actions_count += 1
        if self.close_all_clients_on_service_actions:
            for client in list(self.connected_clients.values()):
                await client.aclose()

    async def service_quit(self) -> None:
        del (
            self.connected_clients,
            self.service_actions_count,
            self.request_received,
            self.request_count,
            self.bad_request_received,
            self.stop_listening,
        )
        await super().service_quit()

    async def on_connection(self, client: AsyncClientInterface[str]) -> None:
        assert client.address not in self.connected_clients
        self.connected_clients[client.address] = client
        await client.send_packet("milk")
        if self.close_all_clients_on_connection:
            await self.backend.sleep(0.1)
            await client.aclose()

    async def on_disconnection(self, client: AsyncClientInterface[str]) -> None:
        del self.connected_clients[client.address]
        del self.request_count[client.address]

    def set_stop_listening_callback(self, stop_listening_callback: Callable[[], None]) -> None:
        super().set_stop_listening_callback(stop_listening_callback)
        self.stop_listening = stop_listening_callback

    async def handle(self, client: AsyncClientInterface[str]) -> AsyncGenerator[None, str]:
        if self.close_client_after_n_request >= 0 and self.request_count[client.address] >= self.close_client_after_n_request:
            await client.aclose()
        request = yield
        self.request_count[client.address] += 1
        match request:
            case "__error__":
                raise RandomError("Sorry man!")
            case "__close__":
                await client.aclose()
                with pytest.raises(ClientClosedError):
                    await client.send_packet("something never sent")
            case "__os_error__":
                raise OSError("Server issue.")
            case "__stop_listening__":
                self.stop_listening()
                await client.send_packet("successfully stop listening")
            case "__wait__":
                request = yield
                self.request_received[client.address].append(request)
                await client.send_packet(f"After wait: {request}")
            case _:
                self.request_received[client.address].append(request)
                await client.send_packet(request.upper())

    async def bad_request(self, client: AsyncClientInterface[str], exc: BaseProtocolParseError) -> None:
        self.bad_request_received[client.address].append(exc)
        await client.send_packet("wrong encoding man.")


class TimeoutRequestHandler(AsyncBaseRequestHandler[str, str]):
    async def handle(self, client: AsyncClientInterface[str]) -> AsyncGenerator[None, str]:
        await client.send_packet("milk")
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(1):
                yield
        await client.send_packet("successfully timed out")

    async def bad_request(self, client: AsyncClientInterface[str], exc: BaseProtocolParseError, /) -> None:
        pass


class CancellationRequestHandler(AsyncBaseRequestHandler[str, str]):
    async def handle(self, client: AsyncClientInterface[str]) -> AsyncGenerator[None, str]:
        await client.send_packet("milk")
        yield
        raise asyncio.CancelledError()

    async def bad_request(self, client: AsyncClientInterface[str], exc: BaseProtocolParseError, /) -> None:
        pass


class InitialHandshakeRequestHandler(AsyncStreamRequestHandler[str, str]):
    backend: AbstractAsyncBackend

    def set_async_backend(self, backend: AbstractAsyncBackend) -> None:
        self.backend = backend

    async def on_connection(self, client: AsyncClientInterface[str]) -> AsyncGenerator[None, str]:
        await client.send_packet("milk")
        try:
            async with self.backend.timeout(1):
                password = yield
        except TimeoutError:
            await client.send_packet("timeout error")
            await client.aclose()
            return
        if password != "chocolate":
            await client.send_packet("wrong password")
            await client.aclose()
            return
        await client.send_packet("you can enter")

    async def handle(self, client: AsyncClientInterface[str]) -> AsyncGenerator[None, str]:
        request = yield
        await client.send_packet(request)

    async def bad_request(self, client: AsyncClientInterface[str], exc: BaseProtocolParseError, /) -> None:
        pass


class InvalidRequestHandler(AsyncStreamRequestHandler[str, str]):
    async def on_connection(self, client: AsyncClientInterface[str]) -> None:
        await client.send_packet("milk")

    async def handle(self, client: AsyncClientInterface[str]) -> AsyncGenerator[None, str]:
        return
        request = yield  # type: ignore[unreachable]
        await client.send_packet(request)

    async def bad_request(self, client: AsyncClientInterface[str], exc: BaseProtocolParseError, /) -> None:
        pass


class ErrorInBadRequestHandler(AsyncStreamRequestHandler[str, str]):
    mute_thrown_exception: bool = False

    async def on_connection(self, client: AsyncClientInterface[str]) -> None:
        await client.send_packet("milk")

    async def handle(self, client: AsyncClientInterface[str]) -> AsyncGenerator[None, str]:
        try:
            request = yield
        except Exception as exc:
            await client.send_packet(f"{exc.__class__.__name__}: {exc}")
            if not self.mute_thrown_exception:
                raise
        else:
            await client.send_packet(request)

    async def bad_request(self, client: AsyncClientInterface[str], exc: BaseProtocolParseError, /) -> None:
        raise RandomError("An error occurred")


class MyAsyncTCPServer(AsyncTCPNetworkServer[str, str]):
    __slots__ = ()


@pytest.mark.asyncio
class TestAsyncTCPNetworkServer(BaseTestAsyncServer):
    @pytest.fixture(params=["NO_SSL", "USE_SSL"])
    @staticmethod
    def use_ssl(request: Any) -> bool:
        match request.param:
            case "NO_SSL":
                return False
            case "USE_SSL":
                return True
            case _:
                raise SystemError

    @pytest.fixture
    @staticmethod
    def backend_kwargs(use_asyncio_transport: bool, use_ssl: bool) -> dict[str, Any]:
        if use_ssl and not use_asyncio_transport:
            pytest.skip("SSL/TLS not supported with transport=False")
        return {"transport": use_asyncio_transport}

    @pytest.fixture
    @staticmethod
    def request_handler(request: Any) -> AsyncBaseRequestHandler[str, str]:
        request_handler_cls: type[AsyncBaseRequestHandler[str, str]] = getattr(request, "param", MyAsyncTCPRequestHandler)
        return request_handler_cls()

    @pytest.fixture
    @staticmethod
    def service_actions_interval(request: Any) -> float | None:
        return getattr(request, "param", None)

    @pytest.fixture
    @staticmethod
    def ssl_handshake_timeout(request: Any) -> float | None:
        return getattr(request, "param", None)

    @pytest_asyncio.fixture
    @staticmethod
    async def server(
        request_handler: MyAsyncTCPRequestHandler,
        localhost_ip: str,
        stream_protocol: StreamProtocol[str, str],
        use_ssl: bool,
        server_ssl_context: ssl.SSLContext,
        service_actions_interval: float | None,
        ssl_handshake_timeout: float | None,
        backend_kwargs: dict[str, Any],
    ) -> AsyncIterator[MyAsyncTCPServer]:
        async with MyAsyncTCPServer(
            localhost_ip,
            0,
            stream_protocol,
            request_handler,
            backlog=1,
            ssl=server_ssl_context if use_ssl else None,
            ssl_handshake_timeout=ssl_handshake_timeout,
            service_actions_interval=service_actions_interval,
            backend_kwargs=backend_kwargs,
        ) as server:
            assert not server.sockets
            assert not server.get_addresses()
            yield server

    @pytest_asyncio.fixture
    @staticmethod
    async def server_address(run_server: asyncio.Event, server: MyAsyncTCPServer) -> tuple[str, int]:
        async with asyncio.timeout(1):
            await run_server.wait()
        assert server.is_serving()
        server_addresses = server.get_addresses()
        assert len(server_addresses) == 1
        return server_addresses[0].for_connection()

    @pytest.fixture
    @staticmethod
    def run_server_and_wait(run_server: None, server_address: Any) -> None:
        pass

    @pytest_asyncio.fixture
    @staticmethod
    async def client_factory(
        server_address: tuple[str, int],
        event_loop: asyncio.AbstractEventLoop,
        use_ssl: bool,
        client_ssl_context: ssl.SSLContext,
    ) -> AsyncIterator[Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]]]:
        async with contextlib.AsyncExitStack() as stack:

            async def factory() -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
                sock = await create_connection(*server_address, event_loop)
                sock.setblocking(False)
                reader, writer = await asyncio.open_connection(
                    sock=sock,
                    ssl=client_ssl_context if use_ssl else None,
                    server_hostname="test.example.com" if use_ssl else None,
                    ssl_handshake_timeout=1 if use_ssl else None,
                )
                stack.push_async_callback(lambda: asyncio.wait_for(writer.wait_closed(), 3))
                stack.callback(writer.close)
                assert await reader.readline() == b"milk\n"
                return reader, writer

            yield factory

    @pytest.mark.parametrize("host", [None, ""], ids=repr)
    async def test____dunder_init____bind_on_all_available_interfaces(
        self,
        host: str | None,
        request_handler: MyAsyncTCPRequestHandler,
        stream_protocol: StreamProtocol[str, str],
        backend_kwargs: dict[str, Any],
    ) -> None:
        async with MyAsyncTCPServer(host, 0, stream_protocol, request_handler, backend_kwargs=backend_kwargs) as s:
            is_up_event = asyncio.Event()
            _ = asyncio.create_task(s.serve_forever(is_up_event=is_up_event))
            async with asyncio.timeout(1):
                await is_up_event.wait()

            assert len(s.sockets) > 0
            assert s.get_protocol() is stream_protocol

            await s.shutdown()

    @pytest.mark.parametrize("ssl_parameter", ["ssl_handshake_timeout", "ssl_shutdown_timeout"])
    async def test____dunder_init____useless_parameter_if_no_ssl_context(
        self,
        ssl_parameter: str,
        request_handler: MyAsyncTCPRequestHandler,
        stream_protocol: StreamProtocol[str, str],
    ) -> None:
        kwargs: dict[str, Any] = {ssl_parameter: 30}
        with pytest.raises(ValueError, match=r"^%s is only meaningful with ssl$" % ssl_parameter):
            _ = MyAsyncTCPServer(None, 0, stream_protocol, request_handler, ssl=None, **kwargs)

    @pytest.mark.parametrize(
        "max_recv_size",
        [
            pytest.param(0, id="null size"),
            pytest.param(-20, id="negative size"),
        ],
    )
    async def test____dunder_init____negative_or_null_recv_size(
        self,
        max_recv_size: int,
        request_handler: MyAsyncTCPRequestHandler,
        stream_protocol: StreamProtocol[str, str],
    ) -> None:
        with pytest.raises(ValueError, match=r"^'max_recv_size' must be a strictly positive integer$"):
            _ = MyAsyncTCPServer(None, 0, stream_protocol, request_handler, max_recv_size=max_recv_size)

    async def test____serve_forever____empty_listener_list(
        self,
        request_handler: MyAsyncTCPRequestHandler,
        stream_protocol: StreamProtocol[str, str],
    ) -> None:
        async with MyAsyncTCPServer(None, 0, stream_protocol, request_handler, backend=NoListenerErrorBackend()) as s:
            with pytest.raises(OSError, match=r"^empty listeners list$"):
                await s.serve_forever()

            assert not s.sockets

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
    @pytest.mark.parametrize("service_actions_interval", [0.1], indirect=True)
    async def test____serve_forever____service_actions(self, request_handler: MyAsyncTCPRequestHandler) -> None:
        await asyncio.sleep(0.2)
        assert request_handler.service_actions_count >= 1

    @pytest.mark.usefixtures("run_server_and_wait")
    @pytest.mark.parametrize("service_actions_interval", [math.inf], indirect=True)
    async def test____serve_forever____service_actions____disabled(self, request_handler: MyAsyncTCPRequestHandler) -> None:
        await asyncio.sleep(1)
        assert request_handler.service_actions_count == 0

    @pytest.mark.usefixtures("run_server_and_wait")
    @pytest.mark.parametrize("service_actions_interval", [0.1], indirect=True)
    async def test____serve_forever____service_actions____crash(
        self,
        request_handler: MyAsyncTCPRequestHandler,
        caplog: pytest.LogCaptureFixture,
        server: MyAsyncTCPServer,
    ) -> None:
        caplog.set_level(logging.ERROR, server.logger.name)
        request_handler.crash_service_actions = True
        await asyncio.sleep(0.5)
        assert request_handler.service_actions_count == 0
        assert "Error occurred in request_handler.service_actions()" in [rec.message for rec in caplog.records]

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

    async def test____serve_forever____several_requests_at_same_time____close_between(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        request_handler: MyAsyncTCPRequestHandler,
    ) -> None:
        reader, writer = await client_factory()
        client_address: tuple[Any, ...] = writer.get_extra_info("sockname")
        request_handler.close_client_after_n_request = 1

        writer.write(b"hello\nworld\n")
        await writer.drain()
        await asyncio.sleep(0.1)

        assert await reader.readline() == b"HELLO\n"
        assert await reader.read() == b""
        assert request_handler.request_received[client_address] == ["hello"]

    async def test____serve_forever____save_request_handler_context(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        request_handler: MyAsyncTCPRequestHandler,
    ) -> None:
        reader, writer = await client_factory()
        client_address: tuple[Any, ...] = writer.get_extra_info("sockname")

        writer.write(b"__wait__\nhello, world!\n")
        await writer.drain()
        await asyncio.sleep(0.1)

        assert await reader.readline() == b"After wait: hello, world!\n"
        assert request_handler.request_received[client_address] == ["hello, world!"]

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

    @pytest.mark.parametrize("mute_thrown_exception", [False, True])
    @pytest.mark.parametrize("request_handler", [ErrorInBadRequestHandler], indirect=True)
    async def test____serve_forever____bad_request____unexpected_error(
        self,
        mute_thrown_exception: bool,
        request_handler: ErrorInBadRequestHandler,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        caplog: pytest.LogCaptureFixture,
        server: MyAsyncTCPServer,
    ) -> None:
        caplog.set_level(logging.ERROR, server.logger.name)
        request_handler.mute_thrown_exception = mute_thrown_exception
        reader, writer = await client_factory()

        writer.write("\u00E9\n".encode("latin-1"))  # StringSerializer does not accept unicode
        await writer.drain()
        await asyncio.sleep(0.1)

        assert await reader.readline() == b"RandomError: An error occurred\n"
        assert await reader.read() == b""
        assert len(caplog.records) == 3

    async def test____serve_forever____bad_request____recursive_traceback_frame_clear_error(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        caplog: pytest.LogCaptureFixture,
        server: MyAsyncTCPServer,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        caplog.set_level(logging.WARNING, server.logger.name)
        reader, writer = await client_factory()

        def infinite_recursion(exc: BaseException) -> None:
            infinite_recursion(exc)

        monkeypatch.setattr(
            f"{AsyncTCPNetworkServer.__module__}._recursively_clear_exception_traceback_frames",
            infinite_recursion,
        )

        writer.write("\u00E9\n".encode("latin-1"))  # StringSerializer does not accept unicode
        await writer.drain()
        await asyncio.sleep(0.1)

        assert await reader.readline() == b"wrong encoding man.\n"
        assert "Recursion depth reached when clearing exception's traceback frames" in [rec.message for rec in caplog.records]

    async def test____serve_forever____unexpected_error_during_process(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        caplog: pytest.LogCaptureFixture,
        server: MyAsyncTCPServer,
    ) -> None:
        caplog.set_level(logging.ERROR, server.logger.name)
        reader, writer = await client_factory()

        writer.write(b"__error__\n")
        await writer.drain()
        await asyncio.sleep(0.1)

        assert await reader.read() == b""
        assert len(caplog.records) == 3

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

    async def test____serve_forever____request_handler_ask_to_stop_accepting_new_connections(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        server: MyAsyncTCPServer,
    ) -> None:
        reader, writer = await client_factory()

        writer.write(b"__stop_listening__\n")
        await writer.drain()
        await asyncio.sleep(0.1)

        assert await reader.readline() == b"successfully stop listening\n"

        assert not server.is_serving()

        with pytest.raises(ExceptionGroup) as exc_info:
            await client_factory()

        errors, exc = exc_info.value.split(ConnectionError)
        assert exc is None
        assert errors is not None

    async def test____serve_forever____close_client_on_connection_hook(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        request_handler: MyAsyncTCPRequestHandler,
    ) -> None:
        request_handler.close_all_clients_on_connection = True
        reader, _ = await client_factory()

        assert await reader.read() == b""

    @pytest.mark.parametrize("request_handler", [TimeoutRequestHandler], indirect=True)
    async def test____serve_forever____throw_cancelled_error(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
    ) -> None:
        reader, _ = await client_factory()

        assert await reader.readline() == b"successfully timed out\n"

    @pytest.mark.parametrize("request_handler", [CancellationRequestHandler], indirect=True)
    async def test____serve_forever____request_handler_is_cancelled(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
    ) -> None:
        reader, writer = await client_factory()

        writer.write(b"something\n")
        await writer.drain()
        await asyncio.sleep(0.1)
        assert await reader.read() == b""

    @pytest.mark.parametrize("request_handler", [InvalidRequestHandler], indirect=True)
    async def test____serve_forever____request_handler_did_not_yield(
        self,
        caplog: pytest.LogCaptureFixture,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        server: MyAsyncTCPServer,
    ) -> None:
        caplog.set_level(logging.ERROR, server.logger.name)
        reader, _ = await client_factory()

        assert await reader.read() == b""
        assert len(caplog.records) == 3

    @pytest.mark.parametrize("request_handler", [InitialHandshakeRequestHandler], indirect=True)
    async def test____serve_forever____request_handler_on_connection_is_async_gen(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
    ) -> None:
        reader, writer = await client_factory()

        writer.write(b"chocolate\n")
        await writer.drain()
        assert await reader.readline() == b"you can enter\n"
        writer.write(b"something\n")
        await writer.drain()
        assert await reader.readline() == b"something\n"

    @pytest.mark.parametrize("request_handler", [InitialHandshakeRequestHandler], indirect=True)
    async def test____serve_forever____request_handler_on_connection_is_async_gen____close_connection(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
    ) -> None:
        reader, writer = await client_factory()

        writer.write(b"something_else\n")
        await writer.drain()
        assert await reader.readline() == b"wrong password\n"
        assert await reader.read() == b""

    @pytest.mark.parametrize("request_handler", [InitialHandshakeRequestHandler], indirect=True)
    async def test____serve_forever____request_handler_on_connection_is_async_gen____throw_cancel_error_within_generator(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
    ) -> None:
        reader, _ = await client_factory()

        assert await reader.readline() == b"timeout error\n"

    @pytest.mark.parametrize("use_ssl", ["USE_SSL"], indirect=True)
    @pytest.mark.parametrize("ssl_handshake_timeout", [pytest.param(0, id="null timeout")])
    async def test____serve_forever____ssl_handshake_timeout_error(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
    ) -> None:
        with pytest.raises(OSError):
            _ = await client_factory()
