# mypy: disable_error_code=override

from __future__ import annotations

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

import pytest
import pytest_asyncio

from .....fixtures.trio import trio_fixture
from .....tools import PlatformMarkers
from ..socket import AsyncStreamSocket
from .base import BaseTestAsyncServer, BaseTestAsyncServerWithAsyncIO, BaseTestAsyncServerWithTrio

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


if sys.platform != "win32":
    from socket import AF_UNIX

    from easynetwork.exceptions import (
        BaseProtocolParseError,
        ClientClosedError,
        IncrementalDeserializeError,
        StreamProtocolParseError,
    )
    from easynetwork.lowlevel._utils import remove_traceback_frames_in_place
    from easynetwork.lowlevel.api_async.backend.abc import IEvent, Task
    from easynetwork.lowlevel.api_async.transports.utils import aclose_forcefully
    from easynetwork.lowlevel.socket import SocketProxy, UnixSocketAddress, enable_socket_linger
    from easynetwork.protocol import AnyStreamProtocolType
    from easynetwork.servers.async_unix_stream import AsyncUnixStreamServer
    from easynetwork.servers.handlers import AsyncStreamClient, AsyncStreamRequestHandler, UNIXClientAttribute

    if TYPE_CHECKING:
        from .....pytest_plugins.unix_sockets import UnixSocketPathFactory

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
            await client.send_packet("response")
            await client.backend().sleep(3600)

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
                await client.backend().sleep(0.2)
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
            await client.backend().sleep(0.2)
            raise RandomError("An error occurred")
            request = yield  # type: ignore[unreachable]
            await client.send_packet(request)

    class MyAsyncUnixStreamServer(AsyncUnixStreamServer[str, str]):
        __slots__ = ()

    _UnixAddressTypeLiteral = Literal["PATHNAME", "ABSTRACT"]

    @pytest.mark.flaky(retries=3, delay=0.1)
    class _BaseTestAsyncUnixStreamServer(BaseTestAsyncServer):
        @pytest.fixture(autouse=True)
        @staticmethod
        def set_default_logger_level(
            caplog: pytest.LogCaptureFixture,
            logger_crash_threshold_level: dict[str, int],
        ) -> None:
            caplog.set_level(logging.WARNING, LOGGER.name)
            logger_crash_threshold_level[LOGGER.name] = logging.WARNING

        @pytest.fixture(
            params=[
                pytest.param("PATHNAME"),
                pytest.param("ABSTRACT", marks=PlatformMarkers.supports_abstract_sockets),
            ]
        )
        @staticmethod
        def use_unix_address_type(request: pytest.FixtureRequest) -> _UnixAddressTypeLiteral:
            match request.param:
                case "PATHNAME" | "ABSTRACT" as param:
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
        def client_factory(
            client_factory_no_handshake: Callable[[], Awaitable[AsyncStreamSocket]],
        ) -> Callable[[], Awaitable[AsyncStreamSocket]]:
            async def factory() -> AsyncStreamSocket:
                sock = await client_factory_no_handshake()
                assert await sock.readline() == b"milk\n"
                return sock

            return factory

        @staticmethod
        async def _wait_client_disconnected(client: AsyncStreamSocket) -> None:
            await client.aclose()
            await client.backend().sleep(0.1)

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
        ) -> None:
            with pytest.raises(ValueError, match=r"^'max_recv_size' must be a strictly positive integer$"):
                _ = MyAsyncUnixStreamServer(
                    unix_socket_path_factory(),
                    stream_protocol,
                    request_handler,
                    max_recv_size=max_recv_size,
                )

        async def test____server_close____while_server_is_running(
            self,
            server: MyAsyncUnixStreamServer,
            run_server: IEvent,
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
            run_server: IEvent,
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
            logger_crash_maximum_nb_lines: dict[str, int],
            mocker: MockerFixture,
        ) -> None:
            caplog.set_level(logging.WARNING, LOGGER.name)
            logger_crash_maximum_nb_lines[LOGGER.name] = 1

            unix_socket_path = server.get_addresses()[0].as_pathname()
            assert unix_socket_path is not None and unix_socket_path.exists()

            mocked_func = mocker.patch(func_with_error, autospec=True, side_effect=OSError(errno.EPERM, os.strerror(errno.EPERM)))
            try:
                await server.server_close()
            finally:
                mocker.stop(mocked_func)

            assert len(caplog.records) == 1
            assert (
                caplog.records[0].getMessage()
                == f"Unable to clean up listening Unix socket {os.fspath(unix_socket_path)!r}: [Errno 1] Operation not permitted"
            )
            assert caplog.records[0].levelno == logging.ERROR
            assert unix_socket_path.exists()

        async def test____serve_forever____server_assignment(
            self,
            server: MyAsyncUnixStreamServer,
            run_server: IEvent,
            request_handler: MyStreamRequestHandler,
        ) -> None:
            await run_server.wait()
            assert request_handler.server == server

        @pytest.mark.parametrize(
            "log_client_connection",
            [True, False, None],
            ids=lambda p: f"log_client_connection=={p}",
            indirect=True,
        )
        async def test____serve_forever____accept_client(
            self,
            log_client_connection: bool | None,
            client_factory: Callable[[], Awaitable[AsyncStreamSocket]],
            request_handler: MyStreamRequestHandler,
            caplog: pytest.LogCaptureFixture,
        ) -> None:
            caplog.set_level(logging.DEBUG, LOGGER.name)
            if log_client_connection is None:
                # Should be True by default
                log_client_connection = True
            client = await client_factory()
            client_address = UnixSocketAddress.from_raw(client.getsockname())
            assert not client_address.is_unnamed()

            assert client_address.as_raw() in request_handler.connected_clients

            await client.send_all(b"hello, world.\n")
            assert await client.readline() == b"HELLO, WORLD.\n"

            assert request_handler.request_received[client_address.as_raw()] == ["hello, world."]

            await self._wait_client_disconnected(client)
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
            server: MyAsyncUnixStreamServer,
            server_address: UnixSocketAddress,
            caplog: pytest.LogCaptureFixture,
        ) -> None:
            from socket import socket as SocketType

            caplog.set_level(logging.WARNING, LOGGER.name)

            socket = SocketType(AF_UNIX)

            # See this thread about SO_LINGER option with null timeout: https://stackoverflow.com/q/3757289
            enable_socket_linger(socket, timeout=0)

            socket.connect(server_address.as_raw())
            socket.close()

            # *This does not happen on all OS*
            # The server will accept a socket which is already in a "Not connected" state
            # and will fail at client initialization when calling socket.getpeername() (errno.ENOTCONN will be raised)
            await server.backend().sleep(0.1)

            assert len(caplog.records) == 0

        async def test____serve_forever____accept_client____server_shutdown(
            self,
            server: MyAsyncUnixStreamServer,
            server_address: UnixSocketAddress,
            request_handler: MyStreamRequestHandler,
        ) -> None:
            from socket import socket as SocketType

            with SocketType(AF_UNIX) as socket:
                socket.connect(server_address.as_raw())
                client_address: str | bytes = socket.getsockname()
                assert client_address not in request_handler.connected_clients

                with server.backend().timeout(1):
                    await server.shutdown()

        async def test____serve_forever____client_extra_attributes(
            self,
            client_factory: Callable[[], Awaitable[AsyncStreamSocket]],
            request_handler: MyStreamRequestHandler,
        ) -> None:

            all_clients: list[AsyncStreamSocket] = [await client_factory() for _ in range(3)]
            assert len(request_handler.connected_clients) == 3

            for client in all_clients:
                client_address: str | bytes = client.getsockname()
                connected_client: AsyncStreamClient[str] = request_handler.connected_clients[client_address]

                assert isinstance(connected_client.extra(UNIXClientAttribute.socket), SocketProxy)
                assert connected_client.extra(UNIXClientAttribute.peer_name).as_raw() == client_address
                assert connected_client.extra(UNIXClientAttribute.local_name).as_raw() == client.getpeername()

                peer_credentials = connected_client.extra(UNIXClientAttribute.peer_credentials)

                if sys.platform.startswith(("darwin", "linux", "openbsd", "netbsd")):
                    assert peer_credentials.pid == os.getpid()
                else:
                    assert peer_credentials.pid is None
                assert peer_credentials.uid == os.geteuid()
                assert peer_credentials.gid == os.getegid()

                # Credentials should be retrieved once.
                assert connected_client.extra(UNIXClientAttribute.peer_credentials) is peer_credentials

        async def test____serve_forever____shutdown_during_loop____kill_client_tasks(
            self,
            server: MyAsyncUnixStreamServer,
            client_factory: Callable[[], Awaitable[AsyncStreamSocket]],
        ) -> None:
            client = await client_factory()

            await server.shutdown()
            await client.backend().sleep(0.3)

            with contextlib.suppress(ConnectionError):
                assert await client.recv(1024) == b""

        async def test____serve_forever____partial_request(
            self,
            server: MyAsyncUnixStreamServer,
            client_factory: Callable[[], Awaitable[AsyncStreamSocket]],
            request_handler: MyStreamRequestHandler,
        ) -> None:
            client = await client_factory()
            client_address: str | bytes = client.getsockname()

            await client.send_all(b"hello")
            await client.backend().sleep(0.1)

            await client.send_all(b", world!\n")

            assert await client.readline() == b"HELLO, WORLD!\n"
            assert request_handler.request_received[client_address] == ["hello, world!"]

        async def test____serve_forever____several_requests_at_same_time(
            self,
            client_factory: Callable[[], Awaitable[AsyncStreamSocket]],
            request_handler: MyStreamRequestHandler,
        ) -> None:
            client = await client_factory()
            client_address: str | bytes = client.getsockname()

            await client.send_all(b"hello\nworld\n")

            assert await client.readline() == b"HELLO\n"
            assert await client.readline() == b"WORLD\n"
            assert request_handler.request_received[client_address] == ["hello", "world"]

        async def test____serve_forever____several_requests_at_same_time____close_between(
            self,
            client_factory: Callable[[], Awaitable[AsyncStreamSocket]],
            request_handler: MyStreamRequestHandler,
        ) -> None:
            client = await client_factory()
            client_address: str | bytes = client.getsockname()
            request_handler.close_client_after_n_request = 1

            await client.send_all(b"hello\nworld\n")

            assert await client.readline() == b"HELLO\n"
            assert await client.recv(1024) == b""
            assert request_handler.request_received[client_address] == ["hello"]

        async def test____serve_forever____save_request_handler_context(
            self,
            client_factory: Callable[[], Awaitable[AsyncStreamSocket]],
            request_handler: MyStreamRequestHandler,
        ) -> None:
            client = await client_factory()
            client_address: str | bytes = client.getsockname()

            await client.send_all(b"__wait__\nhello, world!\n")

            assert await client.readline() == b"After wait: hello, world!\n"
            assert request_handler.request_received[client_address] == ["hello, world!"]

        async def test____serve_forever____bad_request(
            self,
            client_factory: Callable[[], Awaitable[AsyncStreamSocket]],
            request_handler: MyStreamRequestHandler,
        ) -> None:
            client = await client_factory()
            client_address: str | bytes = client.getsockname()

            await client.send_all("\u00e9\n".encode("latin-1"))  # StringSerializer does not accept unicode

            assert await client.readline() == b"wrong encoding man.\n"
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
            client_factory: Callable[[], Awaitable[AsyncStreamSocket]],
            caplog: pytest.LogCaptureFixture,
        ) -> None:
            caplog.set_level(logging.WARNING, LOGGER.name)
            client = await client_factory()

            enable_socket_linger(client, timeout=0)

            await self._wait_client_disconnected(client)

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
            server: MyAsyncUnixStreamServer,
            request_handler: ErrorInRequestHandler,
            client_factory: Callable[[], Awaitable[AsyncStreamSocket]],
            caplog: pytest.LogCaptureFixture,
            logger_crash_maximum_nb_lines: dict[str, int],
        ) -> None:
            caplog.set_level(logging.ERROR, LOGGER.name)
            if not mute_thrown_exception:
                logger_crash_maximum_nb_lines[LOGGER.name] = 3
            request_handler.mute_thrown_exception = mute_thrown_exception
            request_handler.read_on_connection = read_on_connection
            client = await client_factory()

            expected_messages = {
                b"RuntimeError: protocol.build_packet_from_buffer() crashed (caused by SystemError: CRASH)\n",
                b"RuntimeError: protocol.build_packet_from_chunks() crashed (caused by SystemError: CRASH)\n",
            }

            await client.send_all(b"something\n")

            if mute_thrown_exception:
                assert await client.readline() in expected_messages
                await client.send_all(b"something\n")
                assert await client.readline() in expected_messages
                await client.backend().sleep(0.1)
                assert len(caplog.records) == 0  # After two attempts
            else:
                with contextlib.suppress(ConnectionError):
                    assert await client.readline() in expected_messages
                    assert await client.recv(1024) == b""
                await client.backend().sleep(0.1)
                assert len(caplog.records) == 3
                assert caplog.records[1].exc_info is not None
                assert type(caplog.records[1].exc_info[1]) is RuntimeError

        @pytest.mark.parametrize("excgrp", [False, True], ids=lambda p: f"exception_group_raised=={p}")
        async def test____serve_forever____unexpected_error_during_process(
            self,
            excgrp: bool,
            server: MyAsyncUnixStreamServer,
            client_factory: Callable[[], Awaitable[AsyncStreamSocket]],
            caplog: pytest.LogCaptureFixture,
            logger_crash_maximum_nb_lines: dict[str, int],
        ) -> None:
            caplog.set_level(logging.ERROR, LOGGER.name)
            logger_crash_maximum_nb_lines[LOGGER.name] = 3
            client = await client_factory()

            if excgrp:
                await client.send_all(b"__error_excgrp__\n")
            else:
                await client.send_all(b"__error__\n")
            with contextlib.suppress(ConnectionError):
                assert await client.recv(1024) == b""
            await client.backend().sleep(0.1)

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
            server: MyAsyncUnixStreamServer,
            client_factory_no_handshake: Callable[[], Awaitable[AsyncStreamSocket]],
            caplog: pytest.LogCaptureFixture,
            logger_crash_maximum_nb_lines: dict[str, int],
            request_handler: MyStreamRequestHandler,
        ) -> None:
            request_handler.milk_handshake = False
            caplog.set_level(logging.ERROR, LOGGER.name)
            logger_crash_maximum_nb_lines[LOGGER.name] = 1
            client = await client_factory_no_handshake()

            while not request_handler.connected_clients:
                await client.backend().sleep(0.1)

            await client.send_all(b"request\n")
            assert await client.recv(1024) == b""
            await client.backend().sleep(0.1)

            assert len(caplog.records) == 1
            assert (
                caplog.records[0].getMessage()
                == "RuntimeError: protocol.generate_chunks() crashed (caused by SystemError: CRASH)"
            )
            assert caplog.records[0].levelno == logging.ERROR

        async def test____serve_forever____os_error(
            self,
            server: MyAsyncUnixStreamServer,
            caplog: pytest.LogCaptureFixture,
            logger_crash_maximum_nb_lines: dict[str, int],
            client_factory: Callable[[], Awaitable[AsyncStreamSocket]],
        ) -> None:
            caplog.set_level(logging.ERROR, LOGGER.name)
            logger_crash_maximum_nb_lines[LOGGER.name] = 3
            client = await client_factory()

            await client.send_all(b"__os_error__\n")
            with contextlib.suppress(ConnectionError):
                assert await client.recv(1024) == b""
            await client.backend().sleep(0.1)

            assert len(caplog.records) == 3
            assert caplog.records[1].exc_info is not None
            assert type(caplog.records[1].exc_info[1]) is OSError

        @pytest.mark.parametrize("excgrp", [False, True], ids=lambda p: f"exception_group_raised=={p}")
        async def test____serve_forever____use_of_a_closed_client_in_request_handler(
            self,
            excgrp: bool,
            server: MyAsyncUnixStreamServer,
            client_factory: Callable[[], Awaitable[AsyncStreamSocket]],
            caplog: pytest.LogCaptureFixture,
            logger_crash_maximum_nb_lines: dict[str, int],
        ) -> None:
            caplog.set_level(logging.WARNING, LOGGER.name)
            logger_crash_maximum_nb_lines[LOGGER.name] = 1
            client = await client_factory()

            if excgrp:
                await client.send_all(b"__closed_client_error_excgrp__\n")
            else:
                await client.send_all(b"__closed_client_error__\n")
            assert await client.recv(1024) == b""
            await client.backend().sleep(0.1)

            assert len(caplog.records) == 1
            assert caplog.records[0].message.startswith("There have been attempts to do operation on closed client")
            assert caplog.records[0].levelno == logging.WARNING

        async def test____serve_forever____connection_error_in_request_handler(
            self,
            server: MyAsyncUnixStreamServer,
            client_factory: Callable[[], Awaitable[AsyncStreamSocket]],
            caplog: pytest.LogCaptureFixture,
        ) -> None:
            caplog.set_level(logging.WARNING, LOGGER.name)
            client = await client_factory()

            await client.send_all(b"__connection_error__\n")
            assert await client.recv(1024) == b""
            await client.backend().sleep(0.1)

            assert len(caplog.records) == 0

        async def test____serve_forever____connection_error_in_disconnect_hook(
            self,
            client_factory: Callable[[], Awaitable[AsyncStreamSocket]],
            request_handler: MyStreamRequestHandler,
            caplog: pytest.LogCaptureFixture,
            logger_crash_maximum_nb_lines: dict[str, int],
        ) -> None:
            caplog.set_level(logging.WARNING, LOGGER.name)
            logger_crash_maximum_nb_lines[LOGGER.name] = 1
            client = await client_factory()
            request_handler.fail_on_disconnection = True

            await self._wait_client_disconnected(client)

            # ECONNRESET not logged
            assert len(caplog.records) == 1
            assert caplog.records[0].getMessage() == "ConnectionError raised in request_handler.on_disconnection()"
            assert caplog.records[0].levelno == logging.WARNING

        @pytest.mark.parametrize("forcefully_closed", [False, True], ids=lambda p: f"forcefully_closed=={p}")
        async def test____serve_forever____explicitly_closed_by_request_handler(
            self,
            forcefully_closed: bool,
            client_factory: Callable[[], Awaitable[AsyncStreamSocket]],
        ) -> None:
            client = await client_factory()

            if forcefully_closed:
                await client.send_all(b"__close_forcefully__\n")
            else:
                await client.send_all(b"__close__\n")

            assert await client.recv(1024) == b""

        async def test____serve_forever____request_handler_ask_to_stop_accepting_new_connections(
            self,
            client_factory: Callable[[], Awaitable[AsyncStreamSocket]],
            server_task: Task[None],
            server: MyAsyncUnixStreamServer,
        ) -> None:
            client = await client_factory()

            await client.send_all(b"__stop_listening__\n")

            assert await client.readline() == b"successfully stop listening\n"
            await client.backend().sleep(0.1)

            assert not server.is_serving()

            # Unix socket path -> FileNotFoundError
            # Abstract Unix socket -> ConnectionRefusedError
            with pytest.raises((FileNotFoundError, ConnectionError)):
                await client_factory()

            await client.aclose()
            with client.backend().timeout(5):
                await server_task.wait()

        async def test____serve_forever____close_client_on_connection_hook(
            self,
            client_factory: Callable[[], Awaitable[AsyncStreamSocket]],
            request_handler: MyStreamRequestHandler,
        ) -> None:
            request_handler.close_all_clients_on_connection = True
            client = await client_factory()

            assert await client.recv(1024) == b""

        @pytest.mark.parametrize("request_handler", [TimeoutYieldedRequestHandler, TimeoutContextRequestHandler], indirect=True)
        @pytest.mark.parametrize("request_timeout", [0.0, 1.0], ids=lambda p: f"timeout=={p}")
        @pytest.mark.parametrize("timeout_on_second_yield", [False, True], ids=lambda p: f"timeout_on_second_yield=={p}")
        async def test____serve_forever____throw_cancelled_error(
            self,
            request_timeout: float,
            timeout_on_second_yield: bool,
            request_handler: TimeoutYieldedRequestHandler | TimeoutContextRequestHandler,
            client_factory: Callable[[], Awaitable[AsyncStreamSocket]],
        ) -> None:
            request_handler.request_timeout = request_timeout
            request_handler.timeout_on_second_yield = timeout_on_second_yield
            client = await client_factory()

            if timeout_on_second_yield:
                await client.send_all(b"something\n")
                assert await client.readline() == b"something\n"

            assert await client.readline() == b"successfully timed out\n"

        @pytest.mark.parametrize("request_handler", [CancellationRequestHandler], indirect=True)
        async def test____serve_forever____request_handler_is_cancelled(
            self,
            server: MyAsyncUnixStreamServer,
            client_factory: Callable[[], Awaitable[AsyncStreamSocket]],
        ) -> None:
            client = await client_factory()

            await client.send_all(b"something\n")
            assert await client.readline() == b"response\n"

            with client.backend().timeout(1):
                await server.shutdown()

            with contextlib.suppress(ConnectionError):
                assert await client.recv(1024) == b""

        @pytest.mark.parametrize("request_handler", [ErrorBeforeYieldHandler], indirect=True)
        async def test____serve_forever____request_handler_crashed_before_yield(
            self,
            server: MyAsyncUnixStreamServer,
            caplog: pytest.LogCaptureFixture,
            logger_crash_maximum_nb_lines: dict[str, int],
            client_factory: Callable[[], Awaitable[AsyncStreamSocket]],
        ) -> None:
            caplog.set_level(logging.ERROR, LOGGER.name)
            logger_crash_maximum_nb_lines[LOGGER.name] = 3

            with contextlib.suppress(ConnectionError):
                client = await client_factory()
                assert await client.recv(1024) == b""
            await server.backend().sleep(0.1)
            assert len(caplog.records) == 3
            assert caplog.records[1].exc_info is not None
            assert type(caplog.records[1].exc_info[1]) is RandomError

        @pytest.mark.parametrize("request_handler", [RequestRefusedHandler], indirect=True)
        @pytest.mark.parametrize("refuse_after", [0, 5], ids=lambda p: f"refuse_after=={p}")
        async def test____serve_forever____request_handler_did_not_yield(
            self,
            refuse_after: int,
            server: MyAsyncUnixStreamServer,
            request_handler: RequestRefusedHandler,
            caplog: pytest.LogCaptureFixture,
            client_factory: Callable[[], Awaitable[AsyncStreamSocket]],
        ) -> None:
            request_handler.refuse_after = refuse_after
            caplog.set_level(logging.ERROR, LOGGER.name)

            with contextlib.suppress(ConnectionError):
                # If refuse after is equal to zero, client_factory() can raise ConnectionResetError
                client = await client_factory()

                for _ in range(refuse_after):
                    await client.send_all(b"something\n")
                    assert await client.readline() == b"something\n"

                assert await client.recv(1024) == b""

            await server.backend().sleep(0.1)
            assert len(caplog.records) == 0

        @pytest.mark.parametrize("request_handler", [InitialHandshakeRequestHandler], indirect=True)
        @pytest.mark.parametrize("handshake_2fa", [True, False], ids=lambda p: f"handshake_2fa=={p}")
        async def test____serve_forever____request_handler_on_connection_is_async_gen(
            self,
            client_factory: Callable[[], Awaitable[AsyncStreamSocket]],
            handshake_2fa: bool,
            request_handler: InitialHandshakeRequestHandler,
        ) -> None:
            request_handler.handshake_2fa = handshake_2fa
            client = await client_factory()

            await client.send_all(b"chocolate\n")
            if handshake_2fa:
                assert await client.readline() == b"2FA code needed\n"
                await client.send_all(b"42\n")

            assert await client.readline() == b"you can enter\n"
            await client.send_all(b"something\n")
            assert await client.readline() == b"something\n"

        @pytest.mark.parametrize("request_handler", [InitialHandshakeRequestHandler], indirect=True)
        @pytest.mark.parametrize("handshake_2fa", [True, False], ids=lambda p: f"handshake_2fa=={p}")
        async def test____serve_forever____request_handler_on_connection_is_async_gen____close_connection(
            self,
            client_factory: Callable[[], Awaitable[AsyncStreamSocket]],
            handshake_2fa: bool,
            request_handler: InitialHandshakeRequestHandler,
        ) -> None:
            request_handler.handshake_2fa = handshake_2fa
            client = await client_factory()

            if handshake_2fa:
                await client.send_all(b"chocolate\n")
                assert await client.readline() == b"2FA code needed\n"
                await client.send_all(b"123\n")
                assert await client.readline() == b"wrong code\n"
            else:
                await client.send_all(b"something_else\n")
                assert await client.readline() == b"wrong password\n"
            assert await client.recv(1024) == b""

        @pytest.mark.parametrize("request_handler", [InitialHandshakeRequestHandler], indirect=True)
        @pytest.mark.parametrize("handshake_2fa", [True, False], ids=lambda p: f"handshake_2fa=={p}")
        async def test____serve_forever____request_handler_on_connection_is_async_gen____throw_cancel_error_within_generator(
            self,
            client_factory: Callable[[], Awaitable[AsyncStreamSocket]],
            handshake_2fa: bool,
            request_handler: InitialHandshakeRequestHandler,
        ) -> None:
            request_handler.handshake_2fa = handshake_2fa
            client = await client_factory()

            if handshake_2fa:
                await client.send_all(b"chocolate\n")
                assert await client.readline() == b"2FA code needed\n"

            assert await client.readline() == b"timeout error\n"

        @pytest.mark.parametrize("request_handler", [InitialHandshakeRequestHandler], indirect=True)
        async def test____serve_forever____request_handler_on_connection_is_async_gen____exit_before_first_yield(
            self,
            request_handler: InitialHandshakeRequestHandler,
            client_factory: Callable[[], Awaitable[AsyncStreamSocket]],
        ) -> None:
            request_handler.bypass_handshake = True
            client = await client_factory()

            await client.send_all(b"something_else\n")
            assert await client.readline() == b"something_else\n"

    class TestAsyncUnixStreamServerWithAsyncIO(_BaseTestAsyncUnixStreamServer, BaseTestAsyncServerWithAsyncIO):
        @pytest_asyncio.fixture
        @staticmethod
        async def server_not_activated(
            request_handler: MyStreamRequestHandler,
            unix_socket_path_factory: UnixSocketPathFactory,
            stream_protocol: AnyStreamProtocolType[str, str],
        ) -> AsyncIterator[MyAsyncUnixStreamServer]:
            server = MyAsyncUnixStreamServer(
                unix_socket_path_factory(),
                stream_protocol,
                request_handler,
                backend="asyncio",
                backlog=1,
                logger=LOGGER,
            )
            try:
                assert not server.is_listening()
                assert not server.get_sockets()
                assert not server.get_addresses()
                yield server
            finally:
                await server.server_close()

        @pytest_asyncio.fixture
        @staticmethod
        async def server(
            use_unix_address_type: _UnixAddressTypeLiteral,
            request_handler: MyStreamRequestHandler,
            unix_socket_path_factory: UnixSocketPathFactory,
            stream_protocol: AnyStreamProtocolType[str, str],
            log_client_connection: bool | None,
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
                backend="asyncio",
                backlog=1,
                log_client_connection=log_client_connection,
                logger=LOGGER,
            ) as server:
                assert server.is_listening()
                assert server.get_sockets()
                assert server.get_addresses()
                yield server

        @pytest_asyncio.fixture
        @staticmethod
        async def server_address(run_server: IEvent, server: MyAsyncUnixStreamServer) -> UnixSocketAddress:
            with server.backend().timeout(1):
                await run_server.wait()
            assert server.is_serving()
            server_addresses = server.get_addresses()
            assert len(server_addresses) == 1
            return server_addresses[0]

        @pytest_asyncio.fixture
        @staticmethod
        async def client_factory_no_handshake(
            use_unix_address_type: _UnixAddressTypeLiteral,
            unix_socket_path_factory: UnixSocketPathFactory,
            server_address: UnixSocketAddress,
        ) -> AsyncIterator[Callable[[], Awaitable[AsyncStreamSocket]]]:
            import asyncio

            async with contextlib.AsyncExitStack() as stack:

                async def factory() -> AsyncStreamSocket:
                    async with asyncio.timeout(30):
                        # By default, a Unix socket does not have a local name when connecting to a listener.
                        # We need an identifier to recognize them in test cases.
                        if use_unix_address_type == "ABSTRACT":
                            # Let the kernel assign us an abstract socket address.
                            local_path = ""
                        else:
                            # We must assign it to a filepath, even if it will never be used.
                            local_path = unix_socket_path_factory()

                        sock = await AsyncStreamSocket.open_unix_connection(server_address.as_raw(), local_path=local_path)
                        await stack.enter_async_context(sock)
                    return sock

                yield factory

    class TestAsyncUnixStreamServerWithTrio(_BaseTestAsyncUnixStreamServer, BaseTestAsyncServerWithTrio):
        @trio_fixture
        @staticmethod
        async def server_not_activated(
            request_handler: MyStreamRequestHandler,
            unix_socket_path_factory: UnixSocketPathFactory,
            stream_protocol: AnyStreamProtocolType[str, str],
        ) -> AsyncIterator[MyAsyncUnixStreamServer]:
            server = MyAsyncUnixStreamServer(
                unix_socket_path_factory(),
                stream_protocol,
                request_handler,
                backend="trio",
                backlog=1,
                logger=LOGGER,
            )
            try:
                assert not server.is_listening()
                assert not server.get_sockets()
                assert not server.get_addresses()
                yield server
            finally:
                await server.server_close()

        @trio_fixture
        @staticmethod
        async def server(
            use_unix_address_type: _UnixAddressTypeLiteral,
            request_handler: MyStreamRequestHandler,
            unix_socket_path_factory: UnixSocketPathFactory,
            stream_protocol: AnyStreamProtocolType[str, str],
            log_client_connection: bool | None,
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
                backend="trio",
                backlog=1,
                log_client_connection=log_client_connection,
                logger=LOGGER,
            ) as server:
                assert server.is_listening()
                assert server.get_sockets()
                assert server.get_addresses()
                yield server

        @trio_fixture
        @staticmethod
        async def server_address(run_server: IEvent, server: MyAsyncUnixStreamServer) -> UnixSocketAddress:
            with server.backend().timeout(1):
                await run_server.wait()
            assert server.is_serving()
            server_addresses = server.get_addresses()
            assert len(server_addresses) == 1
            return server_addresses[0]

        @trio_fixture
        @staticmethod
        async def client_factory_no_handshake(
            use_unix_address_type: _UnixAddressTypeLiteral,
            unix_socket_path_factory: UnixSocketPathFactory,
            server_address: UnixSocketAddress,
        ) -> AsyncIterator[Callable[[], Awaitable[AsyncStreamSocket]]]:
            import trio

            async with contextlib.AsyncExitStack() as stack:

                async def factory() -> AsyncStreamSocket:
                    with trio.fail_after(30):
                        # By default, a Unix socket does not have a local name when connecting to a listener.
                        # We need an identifier to recognize them in test cases.
                        if use_unix_address_type == "ABSTRACT":
                            # Let the kernel assign us an abstract socket address.
                            local_path = ""
                        else:
                            # We must assign it to a filepath, even if it will never be used.
                            local_path = unix_socket_path_factory()

                        sock = await AsyncStreamSocket.open_unix_connection(server_address.as_raw(), local_path=local_path)
                        await stack.enter_async_context(sock)
                    return sock

                yield factory
