from __future__ import annotations

import asyncio
import collections
import contextlib
import logging
import math
import ssl
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Sequence
from socket import IPPROTO_TCP, TCP_NODELAY
from typing import Any
from weakref import WeakValueDictionary

from easynetwork.api_async.backend.abc import AbstractAsyncBackend
from easynetwork.api_async.server.handler import AsyncBaseRequestHandler, AsyncClientInterface, AsyncStreamRequestHandler
from easynetwork.api_async.server.tcp import AsyncTCPNetworkServer
from easynetwork.exceptions import (
    BaseProtocolParseError,
    ClientClosedError,
    IncrementalDeserializeError,
    StreamProtocolParseError,
)
from easynetwork.protocol import StreamProtocol
from easynetwork.tools.socket import SocketAddress, enable_socket_linger
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
        assert hasattr(self, "backend")
        assert not hasattr(self, "stop_listening")
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
            self.backend,
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
            case "__closed_client_error__":
                await client.aclose()
                await client.send_packet("something never sent")
            case "__connection_error__":
                await client.aclose()  # Close before for graceful close
                raise ConnectionResetError("Because why not?")
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
        assert isinstance(exc, StreamProtocolParseError)
        self.bad_request_received[client.address].append(exc)
        await client.send_packet("wrong encoding man.")


class TimeoutRequestHandler(AsyncStreamRequestHandler[str, str]):
    request_timeout: float = 1.0
    timeout_on_second_yield: bool = False

    def set_async_backend(self, backend: AbstractAsyncBackend) -> None:
        self.backend = backend

    async def on_connection(self, client: AsyncClientInterface[str]) -> None:
        await client.send_packet("milk")

    async def handle(self, client: AsyncClientInterface[str]) -> AsyncGenerator[None, str]:
        if self.timeout_on_second_yield:
            request = yield
            await client.send_packet(request)
        try:
            with pytest.raises(TimeoutError):
                async with self.backend.timeout(self.request_timeout):
                    yield
            await client.send_packet("successfully timed out")
        finally:
            self.request_timeout = 1.0  # Force reset to 1 second in order not to overload the server

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
    bypass_handshake: bool = False

    def set_async_backend(self, backend: AbstractAsyncBackend) -> None:
        self.backend = backend

    async def on_connection(self, client: AsyncClientInterface[str]) -> AsyncGenerator[None, str]:
        await client.send_packet("milk")
        if self.bypass_handshake:
            return
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


class RequestRefusedHandler(AsyncStreamRequestHandler[str, str]):
    refuse_after: int = 2**64

    async def service_init(self) -> None:
        self.request_count: collections.Counter[AsyncClientInterface[str]] = collections.Counter()

    async def on_connection(self, client: AsyncClientInterface[str]) -> None:
        await client.send_packet("milk")

    async def on_disconnection(self, client: AsyncClientInterface[str]) -> None:
        self.request_count.pop(client, None)

    async def handle(self, client: AsyncClientInterface[str]) -> AsyncGenerator[None, str]:
        if self.request_count[client] >= self.refuse_after:
            return
        request = yield
        self.request_count[client] += 1
        await client.send_packet(request)

    async def bad_request(self, client: AsyncClientInterface[str], exc: BaseProtocolParseError, /) -> None:
        pass


class ErrorInRequestHandler(AsyncStreamRequestHandler[str, str]):
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


class ErrorBeforeYieldHandler(AsyncStreamRequestHandler[str, str]):
    async def on_connection(self, client: AsyncClientInterface[str]) -> None:
        await client.send_packet("milk")

    async def handle(self, client: AsyncClientInterface[str]) -> AsyncGenerator[None, str]:
        raise RandomError("An error occurred")
        request = yield  # type: ignore[unreachable]
        await client.send_packet(request)

    async def bad_request(self, client: AsyncClientInterface[str], exc: BaseProtocolParseError, /) -> None:
        pass


class CloseHandleAfterBadRequest(AsyncStreamRequestHandler[str, str]):
    bad_request_return_value: bool | None = None

    async def on_connection(self, client: AsyncClientInterface[str]) -> None:
        await client.send_packet("milk")

    async def handle(self, client: AsyncClientInterface[str]) -> AsyncGenerator[None, str]:
        await client.send_packet("new handle")
        try:
            request = yield
        except GeneratorExit:
            await client.send_packet("GeneratorExit")
            raise
        else:
            await client.send_packet(request)

    async def bad_request(self, client: AsyncClientInterface[str], exc: BaseProtocolParseError) -> bool | None:
        await client.send_packet("wrong encoding")
        return self.bad_request_return_value


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
            stack.enter_context(contextlib.suppress(OSError))

            async def factory() -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
                async with asyncio.timeout(30):
                    sock = await create_connection(*server_address, event_loop)
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
    @pytest.mark.parametrize("log_client_connection", [True, False], ids=lambda p: f"log_client_connection=={p}")
    @pytest.mark.parametrize("use_ssl", ["NO_SSL"], indirect=True)
    async def test____dunder_init____bind_to_all_available_interfaces(
        self,
        host: str | None,
        log_client_connection: bool,
        request_handler: MyAsyncTCPRequestHandler,
        stream_protocol: StreamProtocol[str, str],
        backend_kwargs: dict[str, Any],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        async with MyAsyncTCPServer(
            host,
            0,
            stream_protocol,
            request_handler,
            backend_kwargs=backend_kwargs,
            log_client_connection=log_client_connection,
        ) as s:
            caplog.set_level(logging.DEBUG, s.logger.name)
            is_up_event = asyncio.Event()
            _ = asyncio.create_task(s.serve_forever(is_up_event=is_up_event))
            async with asyncio.timeout(1):
                await is_up_event.wait()

            try:
                assert len(s.get_addresses()) > 0
                assert len(s.sockets) > 0

                port = s.get_addresses()[0].port

                reader, writer = await asyncio.open_connection("localhost", port)

                assert await reader.readline() == b"milk\n"

                client_host, client_port = writer.get_extra_info("sockname")[:2]

                writer.close()
                await writer.wait_closed()
                await asyncio.sleep(0.1)

            finally:
                await s.shutdown()

            expected_accept_message = f"Accepted new connection (address = ({client_host!r}, {client_port}))"
            expected_disconnect_message = f"({client_host!r}, {client_port}) disconnected"
            expected_log_level: int = logging.INFO if log_client_connection else logging.DEBUG

            accept_record = next((record for record in caplog.records if record.message == expected_accept_message), None)
            disconnect_record = next((record for record in caplog.records if record.message == expected_disconnect_message), None)

            assert accept_record is not None and disconnect_record is not None
            assert accept_record.levelno == expected_log_level and disconnect_record.levelno == expected_log_level

    @pytest.mark.parametrize("ssl_parameter", ["ssl_handshake_timeout", "ssl_shutdown_timeout"])
    async def test____dunder_init____useless_parameter_if_no_ssl_context(
        self,
        ssl_parameter: str,
        request_handler: MyAsyncTCPRequestHandler,
        stream_protocol: StreamProtocol[str, str],
    ) -> None:
        kwargs: dict[str, Any] = {ssl_parameter: 30}
        with pytest.raises(ValueError, match=rf"^{ssl_parameter} is only meaningful with ssl$"):
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
        assert await reader.readline() == b"HELLO, WORLD.\n"

        assert request_handler.request_received[client_address] == ["hello, world."]

        writer.close()
        await writer.wait_closed()

        async with asyncio.timeout(1):
            while client_address in request_handler.connected_clients:
                await asyncio.sleep(0.1)

    # skip Windows for this test, the ECONNRESET will happen on socket.send() or socket.recv()
    @pytest.mark.xfail('sys.platform == "win32"', reason="socket.getpeername() works by some magic")
    @pytest.mark.parametrize("socket_family", ["AF_INET"], indirect=True)
    @pytest.mark.parametrize("use_ssl", ["NO_SSL"], indirect=True)
    async def test____serve_forever____accept_client____client_sent_RST_packet_right_after_accept(
        self,
        server_address: tuple[str, int],
        caplog: pytest.LogCaptureFixture,
        server: MyAsyncTCPServer,
    ) -> None:
        from socket import socket as SocketType

        caplog.set_level(logging.WARNING, server.logger.name)
        socket = SocketType()

        # See this thread about SO_LINGER option with null timeout: https://stackoverflow.com/q/3757289
        enable_socket_linger(socket, timeout=0)

        socket.connect(server_address)
        socket.close()  # Sends RST packet instead of FIN because of null timeout linger

        # The server will accept a socket which is already in a "Not connected" state
        # and will fail at client initialization when calling socket.getpeername() (errno.ENOTCONN will be raised)
        await asyncio.sleep(0.1)

        # ENOTCONN error should not create a big Traceback error but only a warning (at least)
        assert len(caplog.records) == 1
        assert caplog.records[0].levelno == logging.WARNING
        assert caplog.records[0].message == "A client connection was interrupted just after listener.accept()"

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
        assert await reader.readline() == b"HELLO\n"
        writer.write(b"world!\n")
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
        await asyncio.sleep(0.1)

        writer.write(b", world!\n")

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
        await asyncio.sleep(0.1)

        assert await reader.readline() == b"wrong encoding man.\n"
        assert request_handler.request_received[client_address] == []
        assert isinstance(request_handler.bad_request_received[client_address][0], StreamProtocolParseError)
        assert isinstance(request_handler.bad_request_received[client_address][0].error, IncrementalDeserializeError)

    @pytest.mark.parametrize("request_handler", [CloseHandleAfterBadRequest], indirect=True)
    @pytest.mark.parametrize("bad_request_return_value", [None, False, True])
    async def test____serve_forever____bad_request____return_value(
        self,
        bad_request_return_value: bool | None,
        request_handler: CloseHandleAfterBadRequest,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
    ) -> None:
        request_handler.bad_request_return_value = bad_request_return_value
        reader, writer = await client_factory()

        assert await reader.readline() == b"new handle\n"
        writer.write("\u00E9\n".encode("latin-1"))  # StringSerializer does not accept unicode
        await asyncio.sleep(0.1)

        assert await reader.readline() == b"wrong encoding\n"
        writer.write(b"something valid\n")
        await asyncio.sleep(0.1)

        if bad_request_return_value in (None, False):
            assert await reader.readline() == b"GeneratorExit\n"
            assert await reader.readline() == b"new handle\n"

        assert await reader.readline() == b"something valid\n"

    @pytest.mark.parametrize("request_handler", [ErrorInRequestHandler], indirect=True)
    async def test____serve_forever____bad_request____unexpected_error(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        caplog: pytest.LogCaptureFixture,
        server: MyAsyncTCPServer,
    ) -> None:
        caplog.set_level(logging.ERROR, server.logger.name)
        reader, writer = await client_factory()

        writer.write("\u00E9\n".encode("latin-1"))  # StringSerializer does not accept unicode
        await asyncio.sleep(0.1)

        with pytest.raises(ConnectionResetError):
            assert await reader.read() == b""
            raise ConnectionResetError
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
        await asyncio.sleep(0.1)

        assert await reader.readline() == b"wrong encoding man.\n"
        assert "Recursion depth reached when clearing exception's traceback frames" in [rec.message for rec in caplog.records]

    @pytest.mark.parametrize("mute_thrown_exception", [False, True])
    @pytest.mark.parametrize("request_handler", [ErrorInRequestHandler], indirect=True)
    @pytest.mark.parametrize("serializer", [pytest.param("invalid", id="serializer_crash")], indirect=True)
    async def test____serve_forever____internal_error(
        self,
        mute_thrown_exception: bool,
        request_handler: ErrorInRequestHandler,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        caplog: pytest.LogCaptureFixture,
        server: MyAsyncTCPServer,
    ) -> None:
        caplog.set_level(logging.ERROR, server.logger.name)
        request_handler.mute_thrown_exception = mute_thrown_exception
        reader, writer = await client_factory()

        writer.write(b"something\n")  # StringSerializer does not accept unicode
        await asyncio.sleep(0.1)

        if mute_thrown_exception:
            assert await reader.readline() == b"SystemError: CRASH\n"
            writer.write(b"something\n")  # StringSerializer does not accept unicode
            await asyncio.sleep(0.1)
            assert await reader.readline() == b"SystemError: CRASH\n"
            assert len(caplog.records) == 0  # After two attempts
        else:
            with pytest.raises(ConnectionResetError):
                assert await reader.readline() == b"SystemError: CRASH\n"
                assert await reader.read() == b""
                raise ConnectionResetError
            assert len(caplog.records) == 3

    async def test____serve_forever____unexpected_error_during_process(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        caplog: pytest.LogCaptureFixture,
        server: MyAsyncTCPServer,
    ) -> None:
        caplog.set_level(logging.ERROR, server.logger.name)
        reader, writer = await client_factory()

        writer.write(b"__error__\n")
        await asyncio.sleep(0.1)

        with pytest.raises(ConnectionResetError):
            assert await reader.read() == b""
            raise ConnectionResetError
        assert len(caplog.records) == 3

    async def test____serve_forever____os_error(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
    ) -> None:
        reader, writer = await client_factory()

        writer.write(b"__os_error__\n")
        await asyncio.sleep(0.1)

        with pytest.raises(ConnectionResetError):
            assert await reader.read() == b""
            raise ConnectionResetError

    async def test____serve_forever____use_of_a_closed_client_in_request_handler(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        caplog: pytest.LogCaptureFixture,
        server: MyAsyncTCPServer,
    ) -> None:
        caplog.set_level(logging.WARNING, server.logger.name)
        reader, writer = await client_factory()
        host, port = writer.get_extra_info("sockname")[:2]

        writer.write(b"__closed_client_error__\n")
        await asyncio.sleep(0.1)

        assert await reader.read() == b""
        assert len(caplog.records) == 1
        assert caplog.records[0].levelno == logging.WARNING
        assert caplog.records[0].message == f"There have been attempts to do operation on closed client ({host!r}, {port})"

    async def test____serve_forever____connection_error_in_request_handler(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        caplog: pytest.LogCaptureFixture,
        server: MyAsyncTCPServer,
    ) -> None:
        caplog.set_level(logging.WARNING, server.logger.name)
        reader, writer = await client_factory()

        writer.write(b"__connection_error__\n")
        await asyncio.sleep(0.1)

        assert await reader.read() == b""
        assert len(caplog.records) == 0

    async def test____serve_forever____explicitly_closed_by_request_handler(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
    ) -> None:
        reader, writer = await client_factory()

        writer.write(b"__close__\n")
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
        await asyncio.sleep(0.1)

        assert await reader.readline() == b"successfully stop listening\n"

        assert not server.is_serving()
        await asyncio.sleep(0.1)

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
    @pytest.mark.parametrize("request_timeout", [0.0, 1.0], ids=lambda p: f"timeout=={p}")
    @pytest.mark.parametrize("timeout_on_second_yield", [False, True], ids=lambda p: f"timeout_on_second_yield=={p}")
    async def test____serve_forever____throw_cancelled_error(
        self,
        request_timeout: float,
        timeout_on_second_yield: bool,
        request_handler: TimeoutRequestHandler,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
    ) -> None:
        request_handler.request_timeout = request_timeout
        request_handler.timeout_on_second_yield = timeout_on_second_yield
        reader, writer = await client_factory()

        if timeout_on_second_yield:
            writer.write(b"something\n")
            assert await reader.readline() == b"something\n"

        assert await reader.readline() == b"successfully timed out\n"

    @pytest.mark.parametrize("request_handler", [CancellationRequestHandler], indirect=True)
    async def test____serve_forever____request_handler_is_cancelled(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
    ) -> None:
        reader, writer = await client_factory()

        writer.write(b"something\n")
        await asyncio.sleep(0.1)
        with pytest.raises(ConnectionResetError):
            assert await reader.read() == b""
            raise ConnectionResetError

    @pytest.mark.parametrize("request_handler", [ErrorBeforeYieldHandler], indirect=True)
    async def test____serve_forever____request_handler_crashed_before_yield(
        self,
        caplog: pytest.LogCaptureFixture,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        server: MyAsyncTCPServer,
    ) -> None:
        caplog.set_level(logging.ERROR, server.logger.name)

        with pytest.raises(ConnectionResetError):
            reader, _ = await client_factory()
            assert await reader.read() == b""
            raise ConnectionResetError
        await asyncio.sleep(0.1)
        assert len(caplog.records) == 3

    @pytest.mark.parametrize("request_handler", [RequestRefusedHandler], indirect=True)
    @pytest.mark.parametrize("refuse_after", [0, 5], ids=lambda p: f"refuse_after=={p}")
    async def test____serve_forever____request_handler_did_not_yield(
        self,
        refuse_after: int,
        request_handler: RequestRefusedHandler,
        caplog: pytest.LogCaptureFixture,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        server: MyAsyncTCPServer,
    ) -> None:
        request_handler.refuse_after = refuse_after
        caplog.set_level(logging.ERROR, server.logger.name)

        with pytest.raises(ConnectionResetError):
            # If refuse after is equal to zero, client_factory() can raise ConnectionResetError
            reader, writer = await client_factory()

            for _ in range(refuse_after):
                writer.write(b"something\n")
                assert await reader.readline() == b"something\n"

            assert await reader.read() == b""

            # Should not go here but just to be sure...
            raise ConnectionResetError
        assert len(caplog.records) == 0

    @pytest.mark.parametrize("request_handler", [InitialHandshakeRequestHandler], indirect=True)
    async def test____serve_forever____request_handler_on_connection_is_async_gen(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
    ) -> None:
        reader, writer = await client_factory()

        writer.write(b"chocolate\n")
        assert await reader.readline() == b"you can enter\n"
        writer.write(b"something\n")
        assert await reader.readline() == b"something\n"

    @pytest.mark.parametrize("request_handler", [InitialHandshakeRequestHandler], indirect=True)
    async def test____serve_forever____request_handler_on_connection_is_async_gen____close_connection(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
    ) -> None:
        reader, writer = await client_factory()

        writer.write(b"something_else\n")
        assert await reader.readline() == b"wrong password\n"
        assert await reader.read() == b""

    @pytest.mark.parametrize("request_handler", [InitialHandshakeRequestHandler], indirect=True)
    async def test____serve_forever____request_handler_on_connection_is_async_gen____throw_cancel_error_within_generator(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
    ) -> None:
        reader, _ = await client_factory()

        assert await reader.readline() == b"timeout error\n"

    @pytest.mark.parametrize("request_handler", [InitialHandshakeRequestHandler], indirect=True)
    async def test____serve_forever____request_handler_on_connection_is_async_gen____exit_before_first_yield(
        self,
        request_handler: InitialHandshakeRequestHandler,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
    ) -> None:
        request_handler.bypass_handshake = True
        reader, writer = await client_factory()

        writer.write(b"something_else\n")
        assert await reader.readline() == b"something_else\n"

    @pytest.mark.parametrize("use_ssl", ["USE_SSL"], indirect=True)
    @pytest.mark.parametrize("ssl_handshake_timeout", [pytest.param(1, id="timeout==1sec")], indirect=True)
    async def test____serve_forever____ssl_handshake_timeout_error(
        self,
        server_address: tuple[str, int],
        event_loop: asyncio.AbstractEventLoop,
        caplog: pytest.LogCaptureFixture,
        server: MyAsyncTCPServer,
    ) -> None:
        caplog.set_level(logging.ERROR, server.logger.name)
        socket = await create_connection(*server_address, event_loop)
        with pytest.raises(OSError):
            # The SSL handshake expects the client to send the list of encryption algorithms.
            # But we won't, so the server will close the connection after 1 second
            # and raise a TimeoutError or ConnectionAbortedError.
            assert await event_loop.sock_recv(socket, 256 * 1024) == b""
            # If sock_recv() did not raise, manually trigger the error
            raise ConnectionAbortedError

        await asyncio.sleep(0.1)
        assert len(caplog.records) == 3
        assert caplog.records[1].message == "Error in client task"
