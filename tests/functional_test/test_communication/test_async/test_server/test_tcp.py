from __future__ import annotations

import asyncio
import collections
import contextlib
import logging
import ssl
import weakref
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Sequence
from socket import IPPROTO_TCP, TCP_NODELAY
from typing import Any
from weakref import WeakValueDictionary

from easynetwork.api_async.server.handler import AsyncStreamClient, AsyncStreamRequestHandler, INETClientAttribute
from easynetwork.api_async.server.tcp import AsyncTCPNetworkServer
from easynetwork.exceptions import (
    BaseProtocolParseError,
    ClientClosedError,
    IncrementalDeserializeError,
    StreamProtocolParseError,
)
from easynetwork.lowlevel.api_async.backend.abc import AsyncBackend
from easynetwork.lowlevel.api_async.backend.factory import current_async_backend
from easynetwork.lowlevel.socket import SocketAddress, enable_socket_linger
from easynetwork.lowlevel.std_asyncio._asyncio_utils import create_connection
from easynetwork.lowlevel.std_asyncio.backend import AsyncIOBackend
from easynetwork.lowlevel.std_asyncio.stream.listener import ListenerSocketAdapter
from easynetwork.lowlevel.std_asyncio.stream.socket import AsyncioTransportStreamSocketAdapter, RawStreamSocketAdapter
from easynetwork.protocol import StreamProtocol

import pytest
import pytest_asyncio

from .....tools import temporary_backend
from .base import BaseTestAsyncServer


class NoListenerErrorBackend(AsyncIOBackend):
    async def create_tcp_listeners(
        self,
        host: str | Sequence[str] | None,
        port: int,
        backlog: int,
        *,
        reuse_port: bool = False,
    ) -> Sequence[ListenerSocketAdapter[AsyncioTransportStreamSocketAdapter | RawStreamSocketAdapter]]:
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
        reuse_port: bool = False,
    ) -> Sequence[ListenerSocketAdapter[AsyncioTransportStreamSocketAdapter]]:
        return []


def client_address(client: AsyncStreamClient[Any]) -> SocketAddress:
    return client.extra(INETClientAttribute.remote_address)


class RandomError(Exception):
    pass


class MyAsyncTCPRequestHandler(AsyncStreamRequestHandler[str, str]):
    connected_clients: WeakValueDictionary[SocketAddress, AsyncStreamClient[str]]
    request_received: collections.defaultdict[tuple[Any, ...], list[str]]
    request_count: collections.Counter[tuple[Any, ...]]
    bad_request_received: collections.defaultdict[tuple[Any, ...], list[BaseProtocolParseError]]
    milk_handshake: bool = True
    close_all_clients_on_connection: bool = False
    close_client_after_n_request: int = -1
    server: AsyncTCPNetworkServer[str, str]
    fail_on_disconnection: bool = False

    async def service_init(self, exit_stack: contextlib.AsyncExitStack, server: AsyncTCPNetworkServer[str, str]) -> None:
        await super().service_init(exit_stack, server)
        self.server = server
        assert isinstance(self.server, AsyncTCPNetworkServer)
        self.connected_clients = WeakValueDictionary()
        self.request_received = collections.defaultdict(list)
        self.request_count = collections.Counter()
        self.bad_request_received = collections.defaultdict(list)
        exit_stack.push_async_callback(self.service_quit)

    async def service_quit(self) -> None:
        del (
            self.connected_clients,
            self.request_received,
            self.request_count,
            self.bad_request_received,
        )

    async def on_connection(self, client: AsyncStreamClient[str]) -> None:
        assert client_address(client) not in self.connected_clients
        self.connected_clients[client_address(client)] = client
        if self.milk_handshake:
            await client.send_packet("milk")
        if self.close_all_clients_on_connection:
            await current_async_backend().sleep(0.1)
            await client.aclose()

    async def on_disconnection(self, client: AsyncStreamClient[str]) -> None:
        del self.connected_clients[client_address(client)]
        del self.request_count[client_address(client)]
        if self.fail_on_disconnection:
            raise ConnectionError("Trying to use the client in a disconnected state")

    async def handle(self, client: AsyncStreamClient[str]) -> AsyncGenerator[None, str]:
        if (
            self.close_client_after_n_request >= 0
            and self.request_count[client_address(client)] >= self.close_client_after_n_request
        ):
            await client.aclose()
        while True:
            async with self.handle_bad_requests(client):
                request = yield
                break
        self.request_count[client_address(client)] += 1
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
                self.server.stop_listening()
                await client.send_packet("successfully stop listening")
            case "__wait__":
                while True:
                    async with self.handle_bad_requests(client):
                        request = yield
                        break
                self.request_received[client_address(client)].append(request)
                await client.send_packet(f"After wait: {request}")
            case _:
                self.request_received[client_address(client)].append(request)
                try:
                    await client.send_packet(request.upper())
                except Exception as exc:
                    msg = f"{exc.__class__.__name__}: {exc}"
                    if exc.__cause__:
                        msg = f"{msg} (caused by {exc.__cause__.__class__.__name__}: {exc.__cause__})"
                    self.server.logger.error(msg, exc_info=exc)
                    await client.aclose()

    @contextlib.asynccontextmanager
    async def handle_bad_requests(self, client: AsyncStreamClient[str]) -> AsyncIterator[None]:
        try:
            yield
        except StreamProtocolParseError as exc:
            self.bad_request_received[client_address(client)].append(exc)
            await client.send_packet("wrong encoding man.")


class TimeoutRequestHandler(AsyncStreamRequestHandler[str, str]):
    request_timeout: float = 1.0
    timeout_on_second_yield: bool = False

    async def service_init(self, exit_stack: contextlib.AsyncExitStack, server: Any) -> None:
        self.backend = current_async_backend()

    async def on_connection(self, client: AsyncStreamClient[str]) -> None:
        await client.send_packet("milk")

    async def handle(self, client: AsyncStreamClient[str]) -> AsyncGenerator[None, str]:
        if self.timeout_on_second_yield:
            request = yield
            await client.send_packet(request)
        try:
            with pytest.raises(TimeoutError):
                with self.backend.timeout(self.request_timeout):
                    yield
            await client.send_packet("successfully timed out")
        finally:
            self.request_timeout = 1.0  # Force reset to 1 second in order not to overload the server


class CancellationRequestHandler(AsyncStreamRequestHandler[str, str]):
    async def on_connection(self, client: AsyncStreamClient[str]) -> None:
        await client.send_packet("milk")

    async def handle(self, client: AsyncStreamClient[str]) -> AsyncGenerator[None, str]:
        yield
        raise asyncio.CancelledError()


class InitialHandshakeRequestHandler(AsyncStreamRequestHandler[str, str]):
    backend: AsyncBackend
    bypass_handshake: bool = False

    async def service_init(self, exit_stack: contextlib.AsyncExitStack, server: Any) -> None:
        self.backend = current_async_backend()

    async def on_connection(self, client: AsyncStreamClient[str]) -> AsyncGenerator[None, str]:
        await client.send_packet("milk")
        if self.bypass_handshake:
            return
        try:
            with self.backend.timeout(1):
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

    async def handle(self, client: AsyncStreamClient[str]) -> AsyncGenerator[None, str]:
        request = yield
        await client.send_packet(request)


class RequestRefusedHandler(AsyncStreamRequestHandler[str, str]):
    refuse_after: int = 2**64

    async def service_init(self, exit_stack: contextlib.AsyncExitStack, server: Any) -> None:
        self.request_count: collections.Counter[AsyncStreamClient[str]] = collections.Counter()

    async def on_connection(self, client: AsyncStreamClient[str]) -> None:
        await client.send_packet("milk")

    async def on_disconnection(self, client: AsyncStreamClient[str]) -> None:
        self.request_count.pop(client, None)

    async def handle(self, client: AsyncStreamClient[str]) -> AsyncGenerator[None, str]:
        if self.request_count[client] >= self.refuse_after:
            await asyncio.sleep(0.2)
            return
        request = yield
        self.request_count[client] += 1
        await client.send_packet(request)


class ErrorInRequestHandler(AsyncStreamRequestHandler[str, str]):
    mute_thrown_exception: bool = False

    async def on_connection(self, client: AsyncStreamClient[str]) -> None:
        await client.send_packet("milk")

    async def handle(self, client: AsyncStreamClient[str]) -> AsyncGenerator[None, str]:
        try:
            request = yield
        except Exception as exc:
            msg = f"{exc.__class__.__name__}: {exc}"
            if exc.__cause__:
                msg = f"{msg} (caused by {exc.__cause__.__class__.__name__}: {exc.__cause__})"
            await client.send_packet(msg)
            if not self.mute_thrown_exception:
                raise
        else:
            await client.send_packet(request)


class ErrorBeforeYieldHandler(AsyncStreamRequestHandler[str, str]):
    async def on_connection(self, client: AsyncStreamClient[str]) -> None:
        await client.send_packet("milk")

    async def handle(self, client: AsyncStreamClient[str]) -> AsyncGenerator[None, str]:
        await asyncio.sleep(0.2)
        raise RandomError("An error occurred")
        request = yield  # type: ignore[unreachable]
        await client.send_packet(request)


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
                pytest.fail(f"Invalid parameter: {request.param}")

    @pytest.fixture
    @staticmethod
    def request_handler(request: Any) -> AsyncStreamRequestHandler[str, str]:
        request_handler_cls: type[AsyncStreamRequestHandler[str, str]] = getattr(request, "param", MyAsyncTCPRequestHandler)
        return request_handler_cls()

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
        ssl_handshake_timeout: float | None,
        caplog: pytest.LogCaptureFixture,
        logger_crash_threshold_level: dict[str, int],
        use_asyncio_transport: bool,  # Only here for dependency
    ) -> AsyncIterator[MyAsyncTCPServer]:
        async with MyAsyncTCPServer(
            localhost_ip,
            0,
            stream_protocol,
            request_handler,
            backlog=1,
            ssl=server_ssl_context if use_ssl else None,
            ssl_handshake_timeout=ssl_handshake_timeout,
        ) as server:
            assert not server.sockets
            assert not server.get_addresses()
            caplog.set_level(logging.INFO, server.logger.name)
            logger_crash_threshold_level[server.logger.name] = logging.WARNING
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
    async def client_factory_no_handshake(
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
                return reader, writer

            yield factory

    @pytest.fixture
    @staticmethod
    def client_factory(
        client_factory_no_handshake: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
    ) -> Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]]:
        async def factory() -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
            reader, writer = await client_factory_no_handshake()
            assert await reader.readline() == b"milk\n"
            return reader, writer

        return factory

    @staticmethod
    async def _wait_client_disconnected(writer: asyncio.StreamWriter, request_handler: MyAsyncTCPRequestHandler) -> None:
        writer.close()
        await writer.wait_closed()
        async with asyncio.timeout(1):
            while request_handler.connected_clients:
                await asyncio.sleep(0.1)

    @pytest.mark.parametrize("host", [None, ""], ids=repr)
    @pytest.mark.parametrize("log_client_connection", [True, False], ids=lambda p: f"log_client_connection=={p}")
    @pytest.mark.usefixtures("use_asyncio_transport")
    async def test____dunder_init____bind_to_all_available_interfaces(
        self,
        host: str | None,
        log_client_connection: bool,
        request_handler: MyAsyncTCPRequestHandler,
        stream_protocol: StreamProtocol[str, str],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        async with MyAsyncTCPServer(
            host,
            0,
            stream_protocol,
            request_handler,
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
        with temporary_backend(NoListenerErrorBackend()):
            async with MyAsyncTCPServer(None, 0, stream_protocol, request_handler) as s:
                with pytest.raises(OSError, match=r"^empty listeners list$"):
                    await s.serve_forever()

                assert not s.sockets

    @pytest.mark.usefixtures("run_server_and_wait")
    async def test____serve_forever____server_assignment(
        self,
        server: MyAsyncTCPServer,
        request_handler: MyAsyncTCPRequestHandler,
    ) -> None:
        assert request_handler.server == server
        assert isinstance(request_handler.server, AsyncTCPNetworkServer)
        assert isinstance(request_handler.server, weakref.ProxyType)

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

        await self._wait_client_disconnected(writer, request_handler)

    # skip Windows for this test, the ECONNRESET will happen on socket.send() or socket.recv()
    @pytest.mark.xfail('sys.platform == "win32"', reason="socket.getpeername() works by some magic")
    @pytest.mark.parametrize("socket_family", ["AF_INET"], indirect=True)
    @pytest.mark.parametrize("use_ssl", ["NO_SSL"], indirect=True)
    async def test____serve_forever____accept_client____client_sent_RST_packet_right_after_accept(
        self,
        server_address: tuple[str, int],
        caplog: pytest.LogCaptureFixture,
        server: MyAsyncTCPServer,
        logger_crash_maximum_nb_lines: dict[str, int],
    ) -> None:
        from socket import socket as SocketType

        caplog.set_level(logging.WARNING, server.logger.name)
        logger_crash_maximum_nb_lines[server.logger.name] = 1

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

    async def test____serve_forever____disable_nagle_algorithm(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        request_handler: MyAsyncTCPRequestHandler,
    ) -> None:
        _ = await client_factory()

        connected_client: AsyncStreamClient[str] = list(request_handler.connected_clients.values())[0]

        tcp_nodelay_state: int = connected_client.extra(INETClientAttribute.socket).getsockopt(IPPROTO_TCP, TCP_NODELAY)

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

    @pytest.mark.parametrize("socket_family", ["AF_INET"], indirect=True)
    @pytest.mark.parametrize("use_ssl", ["NO_SSL"], indirect=True)
    async def test____serve_forever____connection_reset_error(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        caplog: pytest.LogCaptureFixture,
        server: MyAsyncTCPServer,
        request_handler: MyAsyncTCPRequestHandler,
    ) -> None:
        caplog.set_level(logging.WARNING, server.logger.name)
        _, writer = await client_factory()

        enable_socket_linger(writer.get_extra_info("socket"), timeout=0)

        await self._wait_client_disconnected(writer, request_handler)

        # ECONNRESET not logged
        assert len(caplog.records) == 0

    @pytest.mark.parametrize("mute_thrown_exception", [False, True])
    @pytest.mark.parametrize("request_handler", [ErrorInRequestHandler], indirect=True)
    @pytest.mark.parametrize(
        "incremental_serializer",
        [
            pytest.param("invalid", id="serializer_crash"),
            pytest.param("invalid_buffered", id="buffered_serializer_crash"),
        ],
        indirect=True,
    )
    async def test____serve_forever____internal_error(
        self,
        mute_thrown_exception: bool,
        request_handler: ErrorInRequestHandler,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        caplog: pytest.LogCaptureFixture,
        logger_crash_maximum_nb_lines: dict[str, int],
        server: MyAsyncTCPServer,
    ) -> None:
        caplog.set_level(logging.ERROR, server.logger.name)
        if not mute_thrown_exception:
            logger_crash_maximum_nb_lines[server.logger.name] = 3
        request_handler.mute_thrown_exception = mute_thrown_exception
        reader, writer = await client_factory()

        expected_messages = {
            b"RuntimeError: protocol.build_packet_from_buffer() crashed (caused by SystemError: CRASH)\n",
            b"RuntimeError: protocol.build_packet_from_chunks() crashed (caused by SystemError: CRASH)\n",
        }

        writer.write(b"something\n")
        await asyncio.sleep(0.1)

        if mute_thrown_exception:
            assert await reader.readline() in expected_messages
            writer.write(b"something\n")
            await asyncio.sleep(0.1)
            assert await reader.readline() in expected_messages
            assert len(caplog.records) == 0  # After two attempts
        else:
            with pytest.raises(ConnectionResetError):
                assert await reader.readline() in expected_messages
                assert await reader.read() == b""
                raise ConnectionResetError
            assert len(caplog.records) == 3
            assert caplog.records[1].exc_info is not None
            assert type(caplog.records[1].exc_info[1]) is RuntimeError

    async def test____serve_forever____unexpected_error_during_process(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        caplog: pytest.LogCaptureFixture,
        logger_crash_maximum_nb_lines: dict[str, int],
        server: MyAsyncTCPServer,
    ) -> None:
        caplog.set_level(logging.ERROR, server.logger.name)
        logger_crash_maximum_nb_lines[server.logger.name] = 3
        reader, writer = await client_factory()

        writer.write(b"__error__\n")
        await asyncio.sleep(0.1)

        with pytest.raises(ConnectionResetError):
            assert await reader.read() == b""
            raise ConnectionResetError
        assert len(caplog.records) == 3
        assert caplog.records[1].exc_info is not None
        assert type(caplog.records[1].exc_info[1]) is RandomError

    @pytest.mark.parametrize("incremental_serializer", [pytest.param("bad_serialize", id="serializer_crash")], indirect=True)
    async def test____serve_forever____unexpected_error_during_response_serialization(
        self,
        client_factory_no_handshake: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        caplog: pytest.LogCaptureFixture,
        logger_crash_maximum_nb_lines: dict[str, int],
        server: MyAsyncTCPServer,
        request_handler: MyAsyncTCPRequestHandler,
    ) -> None:
        request_handler.milk_handshake = False
        caplog.set_level(logging.ERROR, server.logger.name)
        logger_crash_maximum_nb_lines[server.logger.name] = 1
        reader, writer = await client_factory_no_handshake()

        while not request_handler.connected_clients:
            await asyncio.sleep(0.1)

        writer.write(b"request\n")
        await asyncio.sleep(0.1)

        assert await reader.read() == b""
        assert len(caplog.records) == 1
        assert caplog.records[0].levelno == logging.ERROR
        assert caplog.records[0].message == "RuntimeError: protocol.generate_chunks() crashed (caused by SystemError: CRASH)"

    async def test____serve_forever____os_error(
        self,
        caplog: pytest.LogCaptureFixture,
        logger_crash_maximum_nb_lines: dict[str, int],
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        server: MyAsyncTCPServer,
    ) -> None:
        caplog.set_level(logging.ERROR, server.logger.name)
        logger_crash_maximum_nb_lines[server.logger.name] = 3
        reader, writer = await client_factory()

        writer.write(b"__os_error__\n")
        await asyncio.sleep(0.1)

        with pytest.raises(ConnectionResetError):
            assert await reader.read() == b""
            raise ConnectionResetError

        assert len(caplog.records) == 3
        assert caplog.records[1].exc_info is not None
        assert type(caplog.records[1].exc_info[1]) is OSError

    async def test____serve_forever____use_of_a_closed_client_in_request_handler(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        caplog: pytest.LogCaptureFixture,
        logger_crash_maximum_nb_lines: dict[str, int],
        server: MyAsyncTCPServer,
    ) -> None:
        caplog.set_level(logging.WARNING, server.logger.name)
        logger_crash_maximum_nb_lines[server.logger.name] = 1
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

    async def test____serve_forever____connection_error_in_disconnect_hook(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        request_handler: MyAsyncTCPRequestHandler,
        caplog: pytest.LogCaptureFixture,
        logger_crash_maximum_nb_lines: dict[str, int],
        server: MyAsyncTCPServer,
    ) -> None:
        caplog.set_level(logging.WARNING, server.logger.name)
        logger_crash_maximum_nb_lines[server.logger.name] = 1
        _, writer = await client_factory()
        request_handler.fail_on_disconnection = True

        await self._wait_client_disconnected(writer, request_handler)

        # ECONNRESET not logged
        assert len(caplog.records) == 1
        assert caplog.records[0].levelno == logging.WARNING
        assert caplog.records[0].message == "ConnectionError raised in request_handler.on_disconnection()"

    async def test____serve_forever____explicitly_closed_by_request_handler(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
    ) -> None:
        reader, writer = await client_factory()

        writer.write(b"__close__\n")
        await asyncio.sleep(0.1)

        assert await reader.read() == b""

    async def test____serve_forever____request_handler_ask_to_stop_accepting_new_connections(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        server_task: asyncio.Task[None],
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

        writer.close()
        await writer.wait_closed()
        async with asyncio.timeout(5):
            await asyncio.wait({server_task})

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
        logger_crash_maximum_nb_lines: dict[str, int],
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        server: MyAsyncTCPServer,
    ) -> None:
        caplog.set_level(logging.ERROR, server.logger.name)
        logger_crash_maximum_nb_lines[server.logger.name] = 3

        with pytest.raises(ConnectionResetError):
            reader, _ = await client_factory()
            assert await reader.read() == b""
            raise ConnectionResetError
        await asyncio.sleep(0.1)
        assert len(caplog.records) == 3
        assert caplog.records[1].exc_info is not None
        assert type(caplog.records[1].exc_info[1]) is RandomError

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
        logger_crash_maximum_nb_lines: dict[str, int],
        server: MyAsyncTCPServer,
    ) -> None:
        caplog.set_level(logging.ERROR, server.logger.name)
        logger_crash_maximum_nb_lines[server.logger.name] = 1
        logger_crash_maximum_nb_lines["easynetwork.lowlevel.std_asyncio.stream.listener"] = 1
        socket = await create_connection(*server_address, event_loop)
        with pytest.raises(OSError):
            # The SSL handshake expects the client to send the list of encryption algorithms.
            # But we won't, so the server will close the connection after 1 second
            # and raise a TimeoutError or ConnectionAbortedError.
            assert await event_loop.sock_recv(socket, 256 * 1024) == b""
            # If sock_recv() did not raise, manually trigger the error
            raise ConnectionAbortedError

        await asyncio.sleep(0.1)
        assert len(caplog.records) == 1
        assert caplog.records[0].message == "Error in client task (during TLS handshake)"
