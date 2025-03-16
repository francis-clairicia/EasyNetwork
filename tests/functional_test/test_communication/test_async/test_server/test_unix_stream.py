# mypy: disable_error_code=override

from __future__ import annotations

import asyncio
import collections
import contextlib
import errno
import logging
import os
import stat
import sys
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING, Any, Literal
from weakref import WeakValueDictionary

from easynetwork.exceptions import (
    BaseProtocolParseError,
    ClientClosedError,
    IncrementalDeserializeError,
    StreamProtocolParseError,
)
from easynetwork.lowlevel._utils import remove_traceback_frames_in_place
from easynetwork.lowlevel.api_async.backend._asyncio.backend import AsyncIOBackend
from easynetwork.lowlevel.api_async.transports.utils import aclose_forcefully
from easynetwork.lowlevel.socket import SocketProxy, UnixSocketAddress, enable_socket_linger
from easynetwork.protocol import AnyStreamProtocolType
from easynetwork.servers.async_unix_stream import AsyncUnixStreamServer
from easynetwork.servers.handlers import AsyncStreamClient, AsyncStreamRequestHandler, UNIXClientAttribute

import pytest
import pytest_asyncio

from .....fixtures.socket import AF_UNIX_or_skip
from .....pytest_plugins.unix_sockets import UnixSocketPathFactory
from .....tools import PlatformMarkers
from .base import BaseTestAsyncServer

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def fetch_client_address(client: AsyncStreamClient[Any]) -> str | bytes:
    return client.extra(UNIXClientAttribute.peer_name).as_raw()


class RandomError(Exception):
    pass


LOGGER = logging.getLogger(__name__)


class MyStreamRequestHandler(AsyncStreamRequestHandler[str, str]):
    connected_clients: WeakValueDictionary[str | bytes, AsyncStreamClient[str]]
    request_received: collections.defaultdict[str | bytes, list[str]]
    request_count: collections.Counter[str | bytes]
    bad_request_received: collections.defaultdict[str | bytes, list[BaseProtocolParseError]]
    milk_handshake: bool = True
    close_all_clients_on_connection: bool = False
    close_client_after_n_request: int = -1
    server: AsyncUnixStreamServer[str, str]
    fail_on_disconnection: bool = False

    async def service_init(self, exit_stack: contextlib.AsyncExitStack, server: AsyncUnixStreamServer[str, str]) -> None:
        await super().service_init(exit_stack, server)
        self.server = server
        assert isinstance(self.server, AsyncUnixStreamServer)

        self.connected_clients = WeakValueDictionary()
        exit_stack.callback(self.connected_clients.clear)

        self.request_received = collections.defaultdict(list)
        exit_stack.callback(self.request_received.clear)

        self.request_count = collections.Counter()
        exit_stack.callback(self.request_count.clear)

        self.bad_request_received = collections.defaultdict(list)
        exit_stack.callback(self.bad_request_received.clear)

        exit_stack.push_async_callback(self.service_quit)

    async def service_quit(self) -> None:
        pass

    async def on_connection(self, client: AsyncStreamClient[str]) -> None:
        assert fetch_client_address(client) not in self.connected_clients
        self.connected_clients[fetch_client_address(client)] = client
        if self.milk_handshake:
            await client.send_packet("milk")
        if self.close_all_clients_on_connection:
            await self.server.backend().sleep(0.1)
            await client.aclose()

    async def on_disconnection(self, client: AsyncStreamClient[str]) -> None:
        del self.connected_clients[fetch_client_address(client)]
        del self.request_count[fetch_client_address(client)]
        if self.fail_on_disconnection:
            raise ConnectionError("Trying to use the client in a disconnected state")

    async def handle(self, client: AsyncStreamClient[str]) -> AsyncGenerator[None, str]:
        if (
            self.close_client_after_n_request >= 0
            and self.request_count[fetch_client_address(client)] >= self.close_client_after_n_request
        ):
            await client.aclose()
        while True:
            async with self.handle_bad_requests(client):
                request = yield
                break
        self.request_count[fetch_client_address(client)] += 1
        match request:
            case "__error__":
                raise RandomError("Sorry man!")
            case "__error_excgrp__":
                raise ExceptionGroup("RandomError", [RandomError("Sorry man!")])
            case "__close__" | "__close_forcefully__":
                if request == "__close_forcefully__":
                    await aclose_forcefully(client)
                else:
                    await client.aclose()
                assert client.is_closing()
                with pytest.raises(ClientClosedError):
                    await client.send_packet("something never sent")
            case "__closed_client_error__":
                await client.aclose()
                await client.send_packet("something never sent")
            case "__closed_client_error_excgrp__":
                await client.aclose()
                try:
                    await client.send_packet("something never sent")
                except Exception as exc:
                    raise ExceptionGroup("ClosedClientError", [exc]) from None
            case "__connection_error__":
                await client.aclose()  # Close before for graceful close
                raise ConnectionResetError("Because why not?")
            case "__os_error__":
                raise OSError("Server issue.")
            case "__stop_listening__":
                await self.server.server_close()
                await client.send_packet("successfully stop listening")
            case "__wait__":
                while True:
                    async with self.handle_bad_requests(client):
                        request = yield
                        break
                self.request_received[fetch_client_address(client)].append(request)
                await client.send_packet(f"After wait: {request}")
            case _:
                self.request_received[fetch_client_address(client)].append(request)
                try:
                    await client.send_packet(request.upper())
                except Exception as exc:
                    msg = f"{exc.__class__.__name__}: {exc}"
                    if exc.__cause__:
                        msg = f"{msg} (caused by {exc.__cause__.__class__.__name__}: {exc.__cause__})"
                    LOGGER.error(msg, exc_info=exc)
                    await client.aclose()

    @contextlib.asynccontextmanager
    async def handle_bad_requests(self, client: AsyncStreamClient[str]) -> AsyncIterator[None]:
        try:
            yield
        except StreamProtocolParseError as exc:
            remove_traceback_frames_in_place(exc, 1)
            self.bad_request_received[fetch_client_address(client)].append(exc)
            await client.send_packet("wrong encoding man.")


class TimeoutYieldedRequestHandler(AsyncStreamRequestHandler[str, str]):
    request_timeout: float = 1.0
    timeout_on_second_yield: bool = False

    async def on_connection(self, client: AsyncStreamClient[str]) -> None:
        await client.send_packet("milk")

    async def handle(self, client: AsyncStreamClient[str]) -> AsyncGenerator[float | None, str]:
        if self.timeout_on_second_yield:
            request = yield None
            await client.send_packet(request)
        try:
            with pytest.raises(TimeoutError):
                yield self.request_timeout
            await client.send_packet("successfully timed out")
        finally:
            self.request_timeout = 1.0  # Force reset to 1 second in order not to overload the server


class TimeoutContextRequestHandler(AsyncStreamRequestHandler[str, str]):
    request_timeout: float = 1.0
    timeout_on_second_yield: bool = False

    async def on_connection(self, client: AsyncStreamClient[str]) -> None:
        await client.send_packet("milk")

    async def handle(self, client: AsyncStreamClient[str]) -> AsyncGenerator[None, str]:
        if self.timeout_on_second_yield:
            request = yield
            await client.send_packet(request)
        try:
            with pytest.raises(TimeoutError):
                with client.backend().timeout(self.request_timeout):
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
    bypass_handshake: bool = False
    handshake_2fa: bool = False

    async def on_connection(self, client: AsyncStreamClient[str]) -> AsyncGenerator[float | None, str]:
        await client.send_packet("milk")
        if self.bypass_handshake:
            return
        try:
            password = yield 1.0

            if password != "chocolate":
                await client.send_packet("wrong password")
                await client.aclose()
                return

            if self.handshake_2fa:
                await client.send_packet("2FA code needed")
                code = yield 1.0

                if code != "42":
                    await client.send_packet("wrong code")
                    await client.aclose()
                    return

        except TimeoutError:
            await client.send_packet("timeout error")
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
        exit_stack.callback(self.request_count.clear)

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
    read_on_connection: bool = False

    async def on_connection(self, client: AsyncStreamClient[str]) -> AsyncGenerator[None, str]:
        await client.send_packet("milk")
        if not self.read_on_connection:
            return
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


class MyAsyncUnixStreamServer(AsyncUnixStreamServer[str, str]):
    __slots__ = ()


_UnixAddressTypeLiteral = Literal["PATHNAME", "ABSTRACT"]


@pytest.mark.flaky(retries=3, delay=0.1)
@PlatformMarkers.skipif_platform_win32
class TestAsyncUnixStreamServer(BaseTestAsyncServer):
    @pytest.fixture(
        params=[
            pytest.param("PATHNAME"),
            pytest.param("ABSTRACT", marks=PlatformMarkers.supports_abstract_sockets),
        ]
    )
    @staticmethod
    def use_unix_address_type(
        request: pytest.FixtureRequest,
        event_loop: asyncio.AbstractEventLoop,
    ) -> _UnixAddressTypeLiteral:
        match request.param:
            case "PATHNAME" as param:
                return param
            case "ABSTRACT" as param:
                return param
            case _:
                pytest.fail(f"Invalid use_unix_address_type parameter: {request.param}")

    @pytest.fixture
    @staticmethod
    def request_handler(request: pytest.FixtureRequest) -> AsyncStreamRequestHandler[str, str]:
        request_handler_cls: type[AsyncStreamRequestHandler[str, str]] = getattr(request, "param", MyStreamRequestHandler)
        return request_handler_cls()

    @pytest.fixture
    @staticmethod
    def log_client_connection(request: pytest.FixtureRequest) -> bool | None:
        return getattr(request, "param", None)

    @pytest.fixture
    @staticmethod
    def asyncio_backend() -> AsyncIOBackend:
        return AsyncIOBackend()

    @pytest_asyncio.fixture
    @staticmethod
    async def server_not_activated(
        asyncio_backend: AsyncIOBackend,
        request_handler: MyStreamRequestHandler,
        unix_socket_path_factory: UnixSocketPathFactory,
        stream_protocol: AnyStreamProtocolType[str, str],
        caplog: pytest.LogCaptureFixture,
        logger_crash_threshold_level: dict[str, int],
    ) -> AsyncIterator[MyAsyncUnixStreamServer]:
        server = MyAsyncUnixStreamServer(
            unix_socket_path_factory(),
            stream_protocol,
            request_handler,
            asyncio_backend,
            backlog=1,
            logger=LOGGER,
        )
        try:
            assert not server.is_listening()
            assert not server.get_sockets()
            assert not server.get_addresses()
            caplog.set_level(logging.INFO, LOGGER.name)
            logger_crash_threshold_level[LOGGER.name] = logging.WARNING
            yield server
        finally:
            await server.server_close()

    @pytest_asyncio.fixture
    @staticmethod
    async def server(
        use_unix_address_type: _UnixAddressTypeLiteral,
        asyncio_backend: AsyncIOBackend,
        request_handler: MyStreamRequestHandler,
        unix_socket_path_factory: UnixSocketPathFactory,
        stream_protocol: AnyStreamProtocolType[str, str],
        log_client_connection: bool | None,
        caplog: pytest.LogCaptureFixture,
        logger_crash_threshold_level: dict[str, int],
    ) -> AsyncIterator[MyAsyncUnixStreamServer]:
        if use_unix_address_type == "ABSTRACT":
            # Let the kernel assign us an abstract socket address.
            path = ""
        else:
            path = unix_socket_path_factory()
        async with MyAsyncUnixStreamServer(
            path,
            stream_protocol,
            request_handler,
            asyncio_backend,
            backlog=1,
            log_client_connection=log_client_connection,
            logger=LOGGER,
        ) as server:
            assert server.is_listening()
            assert server.get_sockets()
            assert server.get_addresses()
            caplog.set_level(logging.INFO, LOGGER.name)
            logger_crash_threshold_level[LOGGER.name] = logging.WARNING
            yield server

    @pytest_asyncio.fixture
    @staticmethod
    async def server_address(run_server: asyncio.Event, server: MyAsyncUnixStreamServer) -> UnixSocketAddress:
        async with asyncio.timeout(1):
            await run_server.wait()
        assert server.is_serving()
        server_addresses = server.get_addresses()
        assert len(server_addresses) == 1
        return server_addresses[0]

    @pytest.fixture
    @staticmethod
    def run_server_and_wait(run_server: None, server_address: Any) -> None:
        pass

    @pytest_asyncio.fixture
    @staticmethod
    async def client_factory_no_handshake(
        use_unix_address_type: _UnixAddressTypeLiteral,
        unix_socket_path_factory: UnixSocketPathFactory,
        server_address: UnixSocketAddress,
    ) -> AsyncIterator[Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]]]:
        from socket import SOCK_STREAM, socket as SocketType

        async with contextlib.AsyncExitStack() as stack:
            stack.enter_context(contextlib.suppress(OSError))

            async def factory() -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
                event_loop = asyncio.get_running_loop()
                async with asyncio.timeout(30):
                    sock = SocketType(AF_UNIX_or_skip(), SOCK_STREAM)
                    # By default, a Unix socket does not have a local name when connecting to a listener.
                    # We need an identifier to recognize them in test cases.
                    if use_unix_address_type == "ABSTRACT":
                        # Let the kernel assign us an abstract socket address.
                        sock.bind("")
                    else:
                        # We must assign it to a filepath, even if it will never be used.
                        path = unix_socket_path_factory()
                        sock.bind(path)

                    sock.setblocking(False)
                    await event_loop.sock_connect(sock, server_address.as_raw())
                    reader, writer = await asyncio.open_unix_connection(sock=sock)  # type: ignore[attr-defined,unused-ignore]
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
    async def _wait_client_disconnected(writer: asyncio.StreamWriter) -> None:
        writer.close()
        await writer.wait_closed()
        await asyncio.sleep(0.1)

    @pytest.mark.parametrize(
        "max_recv_size",
        [
            pytest.param(0, id="null size"),
            pytest.param(-20, id="negative size"),
        ],
    )
    async def test____dunder_init____negative_or_null_recv_size(
        self,
        unix_socket_path_factory: UnixSocketPathFactory,
        max_recv_size: int,
        request_handler: MyStreamRequestHandler,
        stream_protocol: AnyStreamProtocolType[str, str],
        asyncio_backend: AsyncIOBackend,
    ) -> None:
        with pytest.raises(ValueError, match=r"^'max_recv_size' must be a strictly positive integer$"):
            _ = MyAsyncUnixStreamServer(
                unix_socket_path_factory(),
                stream_protocol,
                request_handler,
                asyncio_backend,
                max_recv_size=max_recv_size,
            )

    async def test____server_close____while_server_is_running(
        self,
        server: MyAsyncUnixStreamServer,
        run_server: asyncio.Event,
        server_address: UnixSocketAddress,
    ) -> None:
        unix_socket_path = server_address.as_pathname()
        if unix_socket_path:
            assert unix_socket_path.exists()

        await super().test____server_close____while_server_is_running(server, run_server)

        if unix_socket_path:
            # Unix socket has been unlinked.
            assert not unix_socket_path.exists()

    async def test____server_close____while_server_is_running____closed_forcefully(
        self,
        server: MyAsyncUnixStreamServer,
        run_server: asyncio.Event,
        server_address: UnixSocketAddress,
    ) -> None:
        unix_socket_path = server_address.as_pathname()
        if unix_socket_path:
            assert unix_socket_path.exists()

        await super().test____server_close____while_server_is_running____closed_forcefully(server, run_server)

        if unix_socket_path:
            # Unix socket has been unlinked.
            assert not unix_socket_path.exists()

    @pytest.mark.parametrize("use_unix_address_type", ["PATHNAME"], indirect=True)
    async def test____server_close____unix_socket_already_removed(
        self,
        server: MyAsyncUnixStreamServer,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.WARNING, LOGGER.name)

        unix_socket_path = server.get_addresses()[0].as_pathname()
        assert unix_socket_path is not None and unix_socket_path.exists()

        os.unlink(unix_socket_path)
        assert not unix_socket_path.exists()

        await server.server_close()
        assert len(caplog.records) == 0

    @pytest.mark.parametrize("use_unix_address_type", ["PATHNAME"], indirect=True)
    async def test____server_close____unix_socket_removed_then_reused(
        self,
        server: MyAsyncUnixStreamServer,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.WARNING, LOGGER.name)

        unix_socket_path = server.get_addresses()[0].as_pathname()
        assert unix_socket_path is not None and unix_socket_path.exists()

        os.unlink(unix_socket_path)
        unix_socket_path.touch()
        assert stat.S_ISREG(unix_socket_path.stat().st_mode)

        await server.server_close()
        assert len(caplog.records) == 0
        assert unix_socket_path.exists()

    @pytest.mark.parametrize("use_unix_address_type", ["PATHNAME"], indirect=True)
    @pytest.mark.parametrize("func_with_error", ["os.stat", "os.unlink"])
    async def test____server_close____unix_socket_cannot_be_removed(
        self,
        func_with_error: str,
        server: MyAsyncUnixStreamServer,
        caplog: pytest.LogCaptureFixture,
        mocker: MockerFixture,
    ) -> None:
        caplog.set_level(logging.WARNING, LOGGER.name)

        unix_socket_path = server.get_addresses()[0].as_pathname()
        assert unix_socket_path is not None and unix_socket_path.exists()

        mocked_func = mocker.patch(func_with_error, autospec=True, side_effect=OSError(errno.EPERM, os.strerror(errno.EPERM)))
        try:
            await server.server_close()
        finally:
            mocker.stop(mocked_func)

        assert len(caplog.records) == 1
        assert caplog.records[0].levelno == logging.ERROR
        assert (
            caplog.records[0].getMessage()
            == f"Unable to clean up listening Unix socket {os.fspath(unix_socket_path)!r}: [Errno 1] Operation not permitted"
        )
        assert unix_socket_path.exists()

    @pytest.mark.usefixtures("run_server_and_wait")
    async def test____serve_forever____server_assignment(
        self,
        server: MyAsyncUnixStreamServer,
        request_handler: MyStreamRequestHandler,
    ) -> None:
        assert request_handler.server == server
        assert isinstance(request_handler.server, AsyncUnixStreamServer)

    @pytest.mark.parametrize(
        "log_client_connection",
        [True, False, None],
        ids=lambda p: f"log_client_connection=={p}",
        indirect=True,
    )
    async def test____serve_forever____accept_client(
        self,
        log_client_connection: bool | None,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        request_handler: MyStreamRequestHandler,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.DEBUG, LOGGER.name)
        if log_client_connection is None:
            # Should be True by default
            log_client_connection = True
        reader, writer = await client_factory()
        client_address = UnixSocketAddress.from_raw(writer.get_extra_info("sockname"))
        assert not client_address.is_unnamed()

        assert client_address.as_raw() in request_handler.connected_clients

        writer.write(b"hello, world.\n")
        assert await reader.readline() == b"HELLO, WORLD.\n"

        assert request_handler.request_received[client_address.as_raw()] == ["hello, world."]

        await self._wait_client_disconnected(writer)
        assert client_address not in request_handler.connected_clients

        expected_accept_message = f"Accepted new connection (address = {client_address})"
        expected_disconnect_message = f"{client_address} disconnected"
        expected_log_level: int = logging.INFO if log_client_connection else logging.DEBUG

        accept_record = next((record for record in caplog.records if record.getMessage() == expected_accept_message), None)
        disconnect_record = next(
            (record for record in caplog.records if record.getMessage() == expected_disconnect_message), None
        )

        assert accept_record is not None and accept_record.levelno == expected_log_level
        assert disconnect_record is not None and disconnect_record.levelno == expected_log_level

    async def test____serve_forever____accept_client____client_closed_right_after_accept(
        self,
        server_address: UnixSocketAddress,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        from socket import socket as SocketType

        caplog.set_level(logging.WARNING, LOGGER.name)

        socket = SocketType(AF_UNIX_or_skip())

        # See this thread about SO_LINGER option with null timeout: https://stackoverflow.com/q/3757289
        enable_socket_linger(socket, timeout=0)

        socket.connect(server_address.as_raw())
        socket.close()

        # *This does not happen on all OS*
        # The server will accept a socket which is already in a "Not connected" state
        # and will fail at client initialization when calling socket.getpeername() (errno.ENOTCONN will be raised)
        await asyncio.sleep(0.1)

        assert len(caplog.records) == 0

    async def test____serve_forever____accept_client____server_shutdown(
        self,
        server: MyAsyncUnixStreamServer,
        server_address: UnixSocketAddress,
        request_handler: MyStreamRequestHandler,
    ) -> None:
        from socket import socket as SocketType

        with SocketType(AF_UNIX_or_skip()) as socket:
            socket.connect(server_address.as_raw())
            client_address: str | bytes = socket.getsockname()
            assert client_address not in request_handler.connected_clients

            async with asyncio.timeout(1):
                await server.shutdown()

    async def test____serve_forever____client_extra_attributes(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        request_handler: MyStreamRequestHandler,
    ) -> None:

        all_writers: list[asyncio.StreamWriter] = [(await client_factory())[1] for _ in range(3)]
        assert len(request_handler.connected_clients) == 3

        for writer in all_writers:
            client_address: str | bytes = writer.get_extra_info("sockname")
            connected_client: AsyncStreamClient[str] = request_handler.connected_clients[client_address]

            assert isinstance(connected_client.extra(UNIXClientAttribute.socket), SocketProxy)
            assert connected_client.extra(UNIXClientAttribute.peer_name).as_raw() == client_address
            assert connected_client.extra(UNIXClientAttribute.local_name).as_raw() == writer.get_extra_info("peername")

            peer_credentials = connected_client.extra(UNIXClientAttribute.peer_credentials)

            if sys.platform.startswith(("darwin", "linux", "openbsd", "netbsd")):
                assert peer_credentials.pid == os.getpid()
            else:
                assert peer_credentials.pid is None
            assert peer_credentials.uid == os.geteuid()  # type: ignore[attr-defined, unused-ignore]
            assert peer_credentials.gid == os.getegid()  # type: ignore[attr-defined, unused-ignore]

            # Credentials should be retrieved once.
            assert connected_client.extra(UNIXClientAttribute.peer_credentials) is peer_credentials

    async def test____serve_forever____shutdown_during_loop____kill_client_tasks(
        self,
        server: MyAsyncUnixStreamServer,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
    ) -> None:
        reader, _ = await client_factory()

        await server.shutdown()
        await asyncio.sleep(0.3)

        with contextlib.suppress(ConnectionError):
            assert await reader.read() == b""

    async def test____serve_forever____partial_request(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        request_handler: MyStreamRequestHandler,
    ) -> None:
        reader, writer = await client_factory()
        client_address: str | bytes = writer.get_extra_info("sockname")

        writer.write(b"hello")
        await asyncio.sleep(0.1)

        writer.write(b", world!\n")

        assert await reader.readline() == b"HELLO, WORLD!\n"
        assert request_handler.request_received[client_address] == ["hello, world!"]

    async def test____serve_forever____several_requests_at_same_time(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        request_handler: MyStreamRequestHandler,
    ) -> None:
        reader, writer = await client_factory()
        client_address: str | bytes = writer.get_extra_info("sockname")

        writer.write(b"hello\nworld\n")

        assert await reader.readline() == b"HELLO\n"
        assert await reader.readline() == b"WORLD\n"
        assert request_handler.request_received[client_address] == ["hello", "world"]

    async def test____serve_forever____several_requests_at_same_time____close_between(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        request_handler: MyStreamRequestHandler,
    ) -> None:
        reader, writer = await client_factory()
        client_address: str | bytes = writer.get_extra_info("sockname")
        request_handler.close_client_after_n_request = 1

        writer.write(b"hello\nworld\n")

        assert await reader.readline() == b"HELLO\n"
        assert await reader.read() == b""
        assert request_handler.request_received[client_address] == ["hello"]

    async def test____serve_forever____save_request_handler_context(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        request_handler: MyStreamRequestHandler,
    ) -> None:
        reader, writer = await client_factory()
        client_address: str | bytes = writer.get_extra_info("sockname")

        writer.write(b"__wait__\nhello, world!\n")

        assert await reader.readline() == b"After wait: hello, world!\n"
        assert request_handler.request_received[client_address] == ["hello, world!"]

    async def test____serve_forever____bad_request(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        request_handler: MyStreamRequestHandler,
    ) -> None:
        reader, writer = await client_factory()
        client_address: str | bytes = writer.get_extra_info("sockname")

        writer.write("\u00e9\n".encode("latin-1"))  # StringSerializer does not accept unicode

        assert await reader.readline() == b"wrong encoding man.\n"
        assert request_handler.request_received[client_address] == []
        assert isinstance(request_handler.bad_request_received[client_address][0], StreamProtocolParseError)
        assert isinstance(request_handler.bad_request_received[client_address][0].error, IncrementalDeserializeError)

    @pytest.mark.parametrize(
        "request_handler",
        [
            pytest.param(MyStreamRequestHandler, id="during_handle"),
            pytest.param(InitialHandshakeRequestHandler, id="during_on_connection_hook"),
        ],
        indirect=True,
    )
    async def test____serve_forever____connection_reset_error(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.WARNING, LOGGER.name)
        _, writer = await client_factory()

        enable_socket_linger(writer.get_extra_info("socket"), timeout=0)

        await self._wait_client_disconnected(writer)

        # ECONNRESET not logged
        assert len(caplog.records) == 0

    @pytest.mark.parametrize("mute_thrown_exception", [False, True], ids=lambda p: f"mute_thrown_exception=={p}")
    @pytest.mark.parametrize("read_on_connection", [False, True], ids=lambda p: f"read_on_connection=={p}")
    @pytest.mark.parametrize("request_handler", [ErrorInRequestHandler], indirect=True)
    @pytest.mark.parametrize(
        "stream_protocol",
        [
            pytest.param("invalid", id="serializer_crash"),
            pytest.param("invalid_buffered", id="buffered_serializer_crash"),
        ],
        indirect=True,
    )
    async def test____serve_forever____internal_error(
        self,
        mute_thrown_exception: bool,
        read_on_connection: bool,
        request_handler: ErrorInRequestHandler,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        caplog: pytest.LogCaptureFixture,
        logger_crash_maximum_nb_lines: dict[str, int],
    ) -> None:
        caplog.set_level(logging.ERROR, LOGGER.name)
        if not mute_thrown_exception:
            logger_crash_maximum_nb_lines[LOGGER.name] = 3
        request_handler.mute_thrown_exception = mute_thrown_exception
        request_handler.read_on_connection = read_on_connection
        reader, writer = await client_factory()

        expected_messages = {
            b"RuntimeError: protocol.build_packet_from_buffer() crashed (caused by SystemError: CRASH)\n",
            b"RuntimeError: protocol.build_packet_from_chunks() crashed (caused by SystemError: CRASH)\n",
        }

        writer.write(b"something\n")

        if mute_thrown_exception:
            assert await reader.readline() in expected_messages
            writer.write(b"something\n")
            assert await reader.readline() in expected_messages
            await asyncio.sleep(0.1)
            assert len(caplog.records) == 0  # After two attempts
        else:
            with contextlib.suppress(ConnectionError):
                assert await reader.readline() in expected_messages
                assert await reader.read() == b""
            await asyncio.sleep(0.1)
            assert len(caplog.records) == 3
            assert caplog.records[1].exc_info is not None
            assert type(caplog.records[1].exc_info[1]) is RuntimeError

    @pytest.mark.parametrize("excgrp", [False, True], ids=lambda p: f"exception_group_raised=={p}")
    async def test____serve_forever____unexpected_error_during_process(
        self,
        excgrp: bool,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        caplog: pytest.LogCaptureFixture,
        logger_crash_maximum_nb_lines: dict[str, int],
    ) -> None:
        caplog.set_level(logging.ERROR, LOGGER.name)
        logger_crash_maximum_nb_lines[LOGGER.name] = 3
        reader, writer = await client_factory()

        if excgrp:
            writer.write(b"__error_excgrp__\n")
        else:
            writer.write(b"__error__\n")
        with contextlib.suppress(ConnectionError):
            assert await reader.read() == b""
        await asyncio.sleep(0.1)

        assert len(caplog.records) == 3
        assert caplog.records[1].exc_info is not None
        if excgrp:
            assert type(caplog.records[1].exc_info[1]) is ExceptionGroup
            assert type(caplog.records[1].exc_info[1].exceptions[0]) is RandomError
        else:
            assert type(caplog.records[1].exc_info[1]) is RandomError

    @pytest.mark.parametrize("stream_protocol", [pytest.param("bad_serialize", id="serializer_crash")], indirect=True)
    async def test____serve_forever____unexpected_error_during_response_serialization(
        self,
        client_factory_no_handshake: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        caplog: pytest.LogCaptureFixture,
        logger_crash_maximum_nb_lines: dict[str, int],
        request_handler: MyStreamRequestHandler,
    ) -> None:
        request_handler.milk_handshake = False
        caplog.set_level(logging.ERROR, LOGGER.name)
        logger_crash_maximum_nb_lines[LOGGER.name] = 1
        reader, writer = await client_factory_no_handshake()

        while not request_handler.connected_clients:
            await asyncio.sleep(0.1)

        writer.write(b"request\n")
        assert await reader.read() == b""
        await asyncio.sleep(0.1)

        assert len(caplog.records) == 1
        assert caplog.records[0].levelno == logging.ERROR
        assert caplog.records[0].getMessage() == "RuntimeError: protocol.generate_chunks() crashed (caused by SystemError: CRASH)"

    async def test____serve_forever____os_error(
        self,
        caplog: pytest.LogCaptureFixture,
        logger_crash_maximum_nb_lines: dict[str, int],
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
    ) -> None:
        caplog.set_level(logging.ERROR, LOGGER.name)
        logger_crash_maximum_nb_lines[LOGGER.name] = 3
        reader, writer = await client_factory()

        writer.write(b"__os_error__\n")
        with contextlib.suppress(ConnectionError):
            assert await reader.read() == b""
        await asyncio.sleep(0.1)

        assert len(caplog.records) == 3
        assert caplog.records[1].exc_info is not None
        assert type(caplog.records[1].exc_info[1]) is OSError

    @pytest.mark.parametrize("excgrp", [False, True], ids=lambda p: f"exception_group_raised=={p}")
    async def test____serve_forever____use_of_a_closed_client_in_request_handler(
        self,
        excgrp: bool,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        caplog: pytest.LogCaptureFixture,
        logger_crash_maximum_nb_lines: dict[str, int],
    ) -> None:
        caplog.set_level(logging.WARNING, LOGGER.name)
        logger_crash_maximum_nb_lines[LOGGER.name] = 1
        reader, writer = await client_factory()

        if excgrp:
            writer.write(b"__closed_client_error_excgrp__\n")
        else:
            writer.write(b"__closed_client_error__\n")
        assert await reader.read() == b""
        await asyncio.sleep(0.1)

        assert len(caplog.records) == 1
        assert caplog.records[0].levelno == logging.WARNING
        assert caplog.records[0].message.startswith("There have been attempts to do operation on closed client")

    async def test____serve_forever____connection_error_in_request_handler(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.WARNING, LOGGER.name)
        reader, writer = await client_factory()

        writer.write(b"__connection_error__\n")
        assert await reader.read() == b""
        await asyncio.sleep(0.1)

        assert len(caplog.records) == 0

    async def test____serve_forever____connection_error_in_disconnect_hook(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        request_handler: MyStreamRequestHandler,
        caplog: pytest.LogCaptureFixture,
        logger_crash_maximum_nb_lines: dict[str, int],
    ) -> None:
        caplog.set_level(logging.WARNING, LOGGER.name)
        logger_crash_maximum_nb_lines[LOGGER.name] = 1
        _, writer = await client_factory()
        request_handler.fail_on_disconnection = True

        await self._wait_client_disconnected(writer)

        # ECONNRESET not logged
        assert len(caplog.records) == 1
        assert caplog.records[0].levelno == logging.WARNING
        assert caplog.records[0].getMessage() == "ConnectionError raised in request_handler.on_disconnection()"

    @pytest.mark.parametrize("forcefully_closed", [False, True], ids=lambda p: f"forcefully_closed=={p}")
    async def test____serve_forever____explicitly_closed_by_request_handler(
        self,
        forcefully_closed: bool,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
    ) -> None:
        reader, writer = await client_factory()

        if forcefully_closed:
            writer.write(b"__close_forcefully__\n")
        else:
            writer.write(b"__close__\n")

        assert await reader.read() == b""

    async def test____serve_forever____request_handler_ask_to_stop_accepting_new_connections(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        server_task: asyncio.Task[None],
        server: MyAsyncUnixStreamServer,
    ) -> None:
        reader, writer = await client_factory()

        writer.write(b"__stop_listening__\n")

        assert await reader.readline() == b"successfully stop listening\n"
        await asyncio.sleep(0.1)

        assert not server.is_serving()

        # Unix socket path -> FileNotFoundError
        # Abstract Unix socket -> ConnectionRefusedError
        with pytest.raises((FileNotFoundError, ConnectionError)):
            await client_factory()

        writer.close()
        await writer.wait_closed()
        async with asyncio.timeout(5):
            await asyncio.wait({server_task})

    async def test____serve_forever____close_client_on_connection_hook(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        request_handler: MyStreamRequestHandler,
    ) -> None:
        request_handler.close_all_clients_on_connection = True
        reader, _ = await client_factory()

        assert await reader.read() == b""

    @pytest.mark.parametrize("request_handler", [TimeoutYieldedRequestHandler, TimeoutContextRequestHandler], indirect=True)
    @pytest.mark.parametrize("request_timeout", [0.0, 1.0], ids=lambda p: f"timeout=={p}")
    @pytest.mark.parametrize("timeout_on_second_yield", [False, True], ids=lambda p: f"timeout_on_second_yield=={p}")
    async def test____serve_forever____throw_cancelled_error(
        self,
        request_timeout: float,
        timeout_on_second_yield: bool,
        request_handler: TimeoutYieldedRequestHandler | TimeoutContextRequestHandler,
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

        with contextlib.suppress(ConnectionError):
            assert await reader.read() == b""

    @pytest.mark.parametrize("request_handler", [ErrorBeforeYieldHandler], indirect=True)
    async def test____serve_forever____request_handler_crashed_before_yield(
        self,
        caplog: pytest.LogCaptureFixture,
        logger_crash_maximum_nb_lines: dict[str, int],
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
    ) -> None:
        caplog.set_level(logging.ERROR, LOGGER.name)
        logger_crash_maximum_nb_lines[LOGGER.name] = 3

        with contextlib.suppress(ConnectionError):
            reader, _ = await client_factory()
            assert await reader.read() == b""
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
    ) -> None:
        request_handler.refuse_after = refuse_after
        caplog.set_level(logging.ERROR, LOGGER.name)

        with contextlib.suppress(ConnectionError):
            # If refuse after is equal to zero, client_factory() can raise ConnectionResetError
            reader, writer = await client_factory()

            for _ in range(refuse_after):
                writer.write(b"something\n")
                assert await reader.readline() == b"something\n"

            assert await reader.read() == b""

        await asyncio.sleep(0.1)
        assert len(caplog.records) == 0

    @pytest.mark.parametrize("request_handler", [InitialHandshakeRequestHandler], indirect=True)
    @pytest.mark.parametrize("handshake_2fa", [True, False], ids=lambda p: f"handshake_2fa=={p}")
    async def test____serve_forever____request_handler_on_connection_is_async_gen(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        handshake_2fa: bool,
        request_handler: InitialHandshakeRequestHandler,
    ) -> None:
        request_handler.handshake_2fa = handshake_2fa
        reader, writer = await client_factory()

        writer.write(b"chocolate\n")
        if handshake_2fa:
            assert await reader.readline() == b"2FA code needed\n"
            writer.write(b"42\n")

        assert await reader.readline() == b"you can enter\n"
        writer.write(b"something\n")
        assert await reader.readline() == b"something\n"

    @pytest.mark.parametrize("request_handler", [InitialHandshakeRequestHandler], indirect=True)
    @pytest.mark.parametrize("handshake_2fa", [True, False], ids=lambda p: f"handshake_2fa=={p}")
    async def test____serve_forever____request_handler_on_connection_is_async_gen____close_connection(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        handshake_2fa: bool,
        request_handler: InitialHandshakeRequestHandler,
    ) -> None:
        request_handler.handshake_2fa = handshake_2fa
        reader, writer = await client_factory()

        if handshake_2fa:
            writer.write(b"chocolate\n")
            assert await reader.readline() == b"2FA code needed\n"
            writer.write(b"123\n")
            assert await reader.readline() == b"wrong code\n"
        else:
            writer.write(b"something_else\n")
            assert await reader.readline() == b"wrong password\n"
        assert await reader.read() == b""

    @pytest.mark.parametrize("request_handler", [InitialHandshakeRequestHandler], indirect=True)
    @pytest.mark.parametrize("handshake_2fa", [True, False], ids=lambda p: f"handshake_2fa=={p}")
    async def test____serve_forever____request_handler_on_connection_is_async_gen____throw_cancel_error_within_generator(
        self,
        client_factory: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
        handshake_2fa: bool,
        request_handler: InitialHandshakeRequestHandler,
    ) -> None:
        request_handler.handshake_2fa = handshake_2fa
        reader, writer = await client_factory()

        if handshake_2fa:
            writer.write(b"chocolate\n")
            assert await reader.readline() == b"2FA code needed\n"

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
