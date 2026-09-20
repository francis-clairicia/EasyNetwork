from __future__ import annotations

import collections
import contextlib
import logging
import selectors
import ssl
import threading
import time
from collections.abc import Callable, Generator
from socket import IPPROTO_TCP, TCP_NODELAY
from typing import Any
from weakref import WeakValueDictionary

from easynetwork.exceptions import (
    BaseProtocolParseError,
    ClientClosedError,
    IncrementalDeserializeError,
    StreamProtocolParseError,
)
from easynetwork.lowlevel._utils import remove_traceback_frames_in_place
from easynetwork.lowlevel.request_handler import RecvParams
from easynetwork.lowlevel.socket import SocketAddress, SocketProxy, TLSAttribute, enable_socket_linger
from easynetwork.protocol import AnyStreamProtocolType
from easynetwork.servers.handlers import BlockingStreamClient, BlockingStreamRequestHandler, INETClientAttribute
from easynetwork.servers.threaded_tcp import ThreadedTCPNetworkServer
from easynetwork.servers.threads_helper import NetworkServerThread

import pytest

from .....tools import PlatformMarkers
from ..socket import StreamSocket
from .base import BaseTestThreadedServer


def fetch_client_address(client: BlockingStreamClient[Any]) -> SocketAddress:
    return client.extra(INETClientAttribute.remote_address)


class RandomError(Exception):
    pass


LOGGER = logging.getLogger(__name__)


class MyStreamRequestHandler(BlockingStreamRequestHandler[str, str]):
    connected_clients: WeakValueDictionary[tuple[Any, ...], BlockingStreamClient[str]]
    request_received: collections.defaultdict[tuple[Any, ...], list[str]]
    request_count: collections.Counter[tuple[Any, ...]]
    bad_request_received: collections.defaultdict[tuple[Any, ...], list[BaseProtocolParseError]]
    milk_handshake: bool = True
    close_all_clients_on_connection: bool = False
    close_client_after_n_request: int = -1
    server: ThreadedTCPNetworkServer[str, str]
    fail_on_disconnection: bool = False

    def service_init(self, exit_stack: contextlib.ExitStack, server: ThreadedTCPNetworkServer[str, str]) -> None:
        super().service_init(exit_stack, server)
        self.server = server
        assert isinstance(self.server, ThreadedTCPNetworkServer)

        self.connected_clients = WeakValueDictionary()
        exit_stack.callback(self.connected_clients.clear)

        self.request_received = collections.defaultdict(list)
        exit_stack.callback(self.request_received.clear)

        self.request_count = collections.Counter()
        exit_stack.callback(self.request_count.clear)

        self.bad_request_received = collections.defaultdict(list)
        exit_stack.callback(self.bad_request_received.clear)

        exit_stack.callback(self.service_quit)

    def service_quit(self) -> None:
        pass

    def on_connection(self, client: BlockingStreamClient[str]) -> None:
        assert fetch_client_address(client) not in self.connected_clients
        self.connected_clients[fetch_client_address(client)] = client
        if self.milk_handshake:
            client.send_packet("milk")
        if self.close_all_clients_on_connection:
            time.sleep(0.1)
            client.close()

    def on_disconnection(self, client: BlockingStreamClient[str]) -> None:
        del self.connected_clients[fetch_client_address(client)]
        del self.request_count[fetch_client_address(client)]
        if self.fail_on_disconnection:
            raise ConnectionError("Trying to use the client in a disconnected state")

    def handle(self, client: BlockingStreamClient[str]) -> Generator[None, str]:
        if (
            self.close_client_after_n_request >= 0
            and self.request_count[fetch_client_address(client)] >= self.close_client_after_n_request
        ):
            client.close()
        request = yield from self.handle_bad_requests(client)
        self.request_count[fetch_client_address(client)] += 1
        match request:
            case "__error__":
                raise RandomError("Sorry man!")
            case "__error_excgrp__":
                raise ExceptionGroup("RandomError", [RandomError("Sorry man!")])
            case "__close__":
                client.close()
                assert client.is_closing()
                with pytest.raises(ClientClosedError):
                    client.send_packet("something never sent")
            case "__closed_client_error__":
                client.close()
                client.send_packet("something never sent")
            case "__closed_client_error_excgrp__":
                client.close()
                try:
                    client.send_packet("something never sent")
                except Exception as exc:
                    raise ExceptionGroup("ClosedClientError", [exc]) from None
            case "__connection_error__":
                client.close()  # Close before for graceful close
                raise ConnectionResetError("Because why not?")
            case "__os_error__":
                raise OSError("Server issue.")
            case "__stop_listening__":
                self.server.server_close()
                client.send_packet("successfully stop listening")
            case "__wait__":
                request = yield from self.handle_bad_requests(client)
                self.request_received[fetch_client_address(client)].append(request)
                client.send_packet(f"After wait: {request}")
            case _:
                self.request_received[fetch_client_address(client)].append(request)
                try:
                    client.send_packet(request.upper())
                except Exception as exc:
                    msg = f"{exc.__class__.__name__}: {exc}"
                    if exc.__cause__:
                        msg = f"{msg} (caused by {exc.__cause__.__class__.__name__}: {exc.__cause__})"
                    LOGGER.error(msg, exc_info=exc)
                    client.close()

    def handle_bad_requests(self, client: BlockingStreamClient[str]) -> Generator[None, str, str]:
        while True:
            try:
                return (yield)
            except StreamProtocolParseError as exc:
                remove_traceback_frames_in_place(exc, 1)
                self.bad_request_received[fetch_client_address(client)].append(exc)
                client.send_packet("wrong encoding man.")


class TimeoutYieldedRequestHandler(BlockingStreamRequestHandler[str, str]):
    request_timeout: float = 1.0
    timeout_on_second_yield: bool = False

    def on_connection(self, client: BlockingStreamClient[str]) -> None:
        client.send_packet("milk")

    def handle(self, client: BlockingStreamClient[str]) -> Generator[RecvParams | None, str]:
        if self.timeout_on_second_yield:
            request = yield None
            client.send_packet(request)
        try:
            with pytest.raises(TimeoutError):
                yield RecvParams(timeout=self.request_timeout)
            client.send_packet("successfully timed out")
        finally:
            self.request_timeout = 1.0  # Force reset to 1 second in order not to overload the server


class InitialHandshakeRequestHandler(BlockingStreamRequestHandler[str, str]):
    bypass_handshake: bool = False
    handshake_2fa: bool = False

    def on_connection(self, client: BlockingStreamClient[str]) -> Generator[RecvParams | None, str]:
        client.send_packet("milk")
        if self.bypass_handshake:
            return
        try:
            password = yield RecvParams(timeout=1.0)

            if password != "chocolate":
                client.send_packet("wrong password")
                client.close()
                return

            if self.handshake_2fa:
                client.send_packet("2FA code needed")
                code = yield RecvParams(timeout=1.0)

                if code != "42":
                    client.send_packet("wrong code")
                    client.close()
                    return

        except TimeoutError:
            client.send_packet("timeout error")
            client.close()
            return

        client.send_packet("you can enter")

    def handle(self, client: BlockingStreamClient[str]) -> Generator[None, str]:
        request = yield
        client.send_packet(request)


class RequestRefusedHandler(BlockingStreamRequestHandler[str, str]):
    refuse_after: int = 2**64

    def service_init(self, exit_stack: contextlib.ExitStack, server: Any) -> None:
        self.request_count: collections.Counter[BlockingStreamClient[str]] = collections.Counter()
        exit_stack.callback(self.request_count.clear)

    def on_connection(self, client: BlockingStreamClient[str]) -> None:
        client.send_packet("milk")

    def on_disconnection(self, client: BlockingStreamClient[str]) -> None:
        self.request_count.pop(client, None)

    def handle(self, client: BlockingStreamClient[str]) -> Generator[None, str]:
        if self.request_count[client] >= self.refuse_after:
            time.sleep(0.2)
            return
        request = yield
        self.request_count[client] += 1
        client.send_packet(request)


class ErrorInRequestHandler(BlockingStreamRequestHandler[str, str]):
    mute_thrown_exception: bool = False
    read_on_connection: bool = False

    def on_connection(self, client: BlockingStreamClient[str]) -> Generator[None, str]:
        client.send_packet("milk")
        if not self.read_on_connection:
            return
        try:
            request = yield
        except Exception as exc:
            msg = f"{exc.__class__.__name__}: {exc}"
            if exc.__cause__:
                msg = f"{msg} (caused by {exc.__cause__.__class__.__name__}: {exc.__cause__})"
            client.send_packet(msg)
            if not self.mute_thrown_exception:
                raise
        else:
            client.send_packet(request)

    def handle(self, client: BlockingStreamClient[str]) -> Generator[None, str]:
        try:
            request = yield
        except Exception as exc:
            msg = f"{exc.__class__.__name__}: {exc}"
            if exc.__cause__:
                msg = f"{msg} (caused by {exc.__cause__.__class__.__name__}: {exc.__cause__})"
            client.send_packet(msg)
            if not self.mute_thrown_exception:
                raise
        else:
            client.send_packet(request)


class ErrorBeforeYieldHandler(BlockingStreamRequestHandler[str, str]):
    def on_connection(self, client: BlockingStreamClient[str]) -> None:
        client.send_packet("milk")

    def handle(self, client: BlockingStreamClient[str]) -> Generator[None, str]:
        time.sleep(0.2)
        raise RandomError("An error occurred")
        request = yield  # type: ignore[unreachable]
        client.send_packet(request)


class MyTCPServer(ThreadedTCPNetworkServer[str, str]):
    __slots__ = ()


@pytest.mark.flaky(retries=3, delay=0.1)
class TestThreadedTCPNetworkServer(BaseTestThreadedServer):
    @pytest.fixture(autouse=True)
    @staticmethod
    def set_default_logger_level(
        caplog: pytest.LogCaptureFixture,
        logger_crash_threshold_level: dict[str, int],
    ) -> None:
        caplog.set_level(logging.WARNING, LOGGER.name)
        logger_crash_threshold_level[LOGGER.name] = logging.WARNING

    @pytest.fixture
    @staticmethod
    def server_backlog(request: pytest.FixtureRequest) -> int | None:
        backlog = getattr(request, "param", 1)
        return int(backlog) if backlog is not None else None

    @pytest.fixture(params=["NO_SSL", "USE_SSL"])
    @staticmethod
    def use_ssl(request: pytest.FixtureRequest) -> bool:
        match request.param:
            case "NO_SSL":
                return False
            case "USE_SSL":
                return True
            case _:
                pytest.fail(f"Invalid use_ssl parameter: {request.param}")

    @pytest.fixture
    @staticmethod
    def client_ssl_context(
        client_ssl_context: ssl.SSLContext | None,
        use_ssl: bool,
    ) -> ssl.SSLContext | None:
        if not use_ssl:
            return None
        if client_ssl_context is None:
            pytest.skip("trustme is not installed")
        return client_ssl_context

    @pytest.fixture
    @staticmethod
    def server_ssl_context(
        server_ssl_context: ssl.SSLContext | None,
        use_ssl: bool,
    ) -> ssl.SSLContext | None:
        if not use_ssl:
            return None
        if server_ssl_context is None:
            pytest.skip("trustme is not installed")
        elif hasattr(ssl, "OP_IGNORE_UNEXPECTED_EOF"):
            # Remove this option for non-regression
            server_ssl_context.options &= ~ssl.OP_IGNORE_UNEXPECTED_EOF
        return server_ssl_context

    @pytest.fixture
    @staticmethod
    def request_handler(request: pytest.FixtureRequest) -> BlockingStreamRequestHandler[str, str]:
        request_handler_cls: type[BlockingStreamRequestHandler[str, str]] = getattr(request, "param", MyStreamRequestHandler)
        return request_handler_cls()

    @pytest.fixture
    @staticmethod
    def ssl_handshake_timeout(request: pytest.FixtureRequest) -> float | None:
        return getattr(request, "param", None)

    @pytest.fixture
    @staticmethod
    def ssl_standard_compatible(request: pytest.FixtureRequest) -> bool | None:
        return getattr(request, "param", None)

    @pytest.fixture
    @staticmethod
    def log_client_connection(request: pytest.FixtureRequest) -> bool | None:
        return getattr(request, "param", None)

    @pytest.fixture
    @staticmethod
    def server_not_activated(
        request_handler: MyStreamRequestHandler,
        localhost_ip: str,
        stream_protocol: AnyStreamProtocolType[str, str],
        server_backlog: int,
    ) -> Generator[MyTCPServer]:
        server = MyTCPServer(
            localhost_ip,
            0,
            stream_protocol,
            request_handler,
            backlog=server_backlog,
            logger=LOGGER,
        )
        try:
            assert not server.is_listening()
            assert not server.get_sockets()
            assert not server.get_addresses()
            yield server
        finally:
            server.server_close()

    @pytest.fixture
    @staticmethod
    def server(
        selector_factory: Callable[[], selectors.BaseSelector],
        request_handler: MyStreamRequestHandler,
        localhost_ip: str,
        stream_protocol: AnyStreamProtocolType[str, str],
        server_backlog: int,
        server_ssl_context: ssl.SSLContext | None,
        ssl_handshake_timeout: float | None,
        ssl_standard_compatible: bool | None,
        log_client_connection: bool | None,
    ) -> Generator[MyTCPServer]:
        with MyTCPServer(
            localhost_ip,
            0,
            stream_protocol,
            request_handler,
            backlog=server_backlog,
            ssl=server_ssl_context,
            ssl_handshake_timeout=ssl_handshake_timeout,
            ssl_standard_compatible=ssl_standard_compatible,
            selector_factory=selector_factory,
            log_client_connection=log_client_connection,
            logger=LOGGER,
        ) as server:
            assert server.is_listening()
            assert server.get_sockets()
            assert server.get_addresses()
            yield server

    @pytest.fixture
    @staticmethod
    def server_address(run_server: threading.Event, server: MyTCPServer) -> tuple[str, int]:
        run_server.wait(1.0)
        assert server.is_serving()
        server_addresses = server.get_addresses()
        assert len(server_addresses) == 1
        return server_addresses[0].for_connection()

    @pytest.fixture
    @staticmethod
    def client_factory_no_handshake(
        server_address: tuple[str, int],
        client_ssl_context: ssl.SSLContext | None,
    ) -> Generator[Callable[[], StreamSocket]]:

        with contextlib.ExitStack() as stack:

            def factory() -> StreamSocket:
                sock = StreamSocket.open_tcp_connection(
                    *server_address,
                    connect_timeout=30.0,
                    ssl_context=client_ssl_context,
                    server_hostname="test.example.com" if client_ssl_context else None,
                    ssl_handshake_timeout=1.0 if client_ssl_context else None,
                )
                stack.enter_context(sock)

                sock.set_timeout(10.0)
                return sock

            yield factory

    @pytest.fixture
    @staticmethod
    def client_factory(
        client_factory_no_handshake: Callable[[], StreamSocket],
    ) -> Callable[[], StreamSocket]:
        def factory() -> StreamSocket:
            sock = client_factory_no_handshake()
            assert sock.readline() == b"milk\n"
            return sock

        return factory

    @staticmethod
    def _wait_client_disconnected(client: StreamSocket) -> None:
        client.close()
        time.sleep(0.1)

    @pytest.mark.parametrize("host", [None, ""], ids=repr)
    def test____dunder_init____bind_to_all_available_interfaces(
        self,
        host: str | None,
        request_handler: MyStreamRequestHandler,
        stream_protocol: AnyStreamProtocolType[str, str],
    ) -> None:
        with MyTCPServer(
            host,
            0,
            stream_protocol,
            request_handler,
            logger=LOGGER,
        ) as s:

            thread = NetworkServerThread(s)
            thread.start()

            try:
                assert len(s.get_addresses()) > 0
                assert len(s.get_sockets()) > 0

                port = s.get_addresses()[0].port

                with StreamSocket.open_tcp_connection("localhost", port) as client:
                    assert client.readline() == b"milk\n"

            finally:
                thread.join()

    def test____serve_forever____server_assignment(
        self,
        server: MyTCPServer,
        run_server: threading.Event,
        request_handler: MyStreamRequestHandler,
    ) -> None:
        run_server.wait()
        assert request_handler.server == server

    @pytest.mark.parametrize(
        "log_client_connection",
        [True, False, None],
        ids=lambda p: f"log_client_connection__{p}",
        indirect=True,
    )
    @pytest.mark.parametrize(
        "server_backlog",
        [None, 1, 0],
        ids=lambda p: f"server_backlog__{p}",
        indirect=True,
    )
    def test____serve_forever____accept_client(
        self,
        log_client_connection: bool | None,
        client_factory: Callable[[], StreamSocket],
        request_handler: MyStreamRequestHandler,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.DEBUG, LOGGER.name)
        if log_client_connection is None:
            # Should be True by default
            log_client_connection = True
        client = client_factory()
        client_address: tuple[Any, ...] = client.getsockname()
        client_host, client_port = client_address[:2]

        assert client_address in request_handler.connected_clients

        client.send_all(b"hello, world.\n")
        assert client.readline() == b"HELLO, WORLD.\n"

        assert request_handler.request_received[client_address] == ["hello, world."]

        self._wait_client_disconnected(client)
        assert client_address not in request_handler.connected_clients

        expected_accept_message = f"Accepted new connection (address = ({client_host!r}, {client_port}))"
        expected_disconnect_message = f"({client_host!r}, {client_port}) disconnected"
        expected_log_level: int = logging.INFO if log_client_connection else logging.DEBUG

        accept_record = next((record for record in caplog.records if record.getMessage() == expected_accept_message), None)
        disconnect_record = next(
            (record for record in caplog.records if record.getMessage() == expected_disconnect_message), None
        )

        assert accept_record is not None and accept_record.levelno == expected_log_level
        assert disconnect_record is not None and disconnect_record.levelno == expected_log_level

    # skip Windows for this test, the ECONNRESET will happen on socket.send() or socket.recv()
    @PlatformMarkers.skipif_platform_win32_because("socket.getpeername() works by some magic on Windows")
    @pytest.mark.parametrize("socket_family", ["AF_INET"], indirect=True)
    def test____serve_forever____accept_client____client_sent_RST_packet_right_after_accept(
        self,
        server: MyTCPServer,
        server_address: tuple[str, int],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        from socket import socket as SocketType

        caplog.set_level(logging.WARNING, LOGGER.name)

        socket = SocketType()

        # See this thread about SO_LINGER option with null timeout: https://stackoverflow.com/q/3757289
        enable_socket_linger(socket, timeout=0)

        socket.connect(server_address)
        socket.close()  # Sends RST packet instead of FIN because of null timeout linger

        # The server will accept a socket which is already in a "Not connected" state
        # and will fail at client initialization when calling socket.getpeername() (errno.ENOTCONN will be raised)
        time.sleep(0.1)

        # On Linux: ENOTCONN error should not create a big Traceback error
        # On BSD: ECONNABORTED error on accept() should not create a big Traceback error
        assert len(caplog.records) == 0

    @pytest.mark.parametrize("socket_family", ["AF_INET"], indirect=True)
    def test____serve_forever____accept_client____server_shutdown(
        self,
        server: MyTCPServer,
        server_address: tuple[str, int],
        request_handler: MyStreamRequestHandler,
    ) -> None:
        from socket import socket as SocketType

        with SocketType() as socket:
            socket.connect(server_address)
            client_address: tuple[Any, ...] = socket.getsockname()
            assert client_address not in request_handler.connected_clients

            server.shutdown(timeout=1.0)

    def test____serve_forever____client_extra_attributes(
        self,
        client_factory: Callable[[], StreamSocket],
        request_handler: MyStreamRequestHandler,
        use_ssl: bool,
    ) -> None:
        all_clients: list[StreamSocket] = [client_factory() for _ in range(3)]
        assert len(request_handler.connected_clients) == 3

        for client in all_clients:
            client_address: tuple[Any, ...] = client.getsockname()
            connected_client: BlockingStreamClient[str] = request_handler.connected_clients[client_address]

            assert isinstance(connected_client.extra(INETClientAttribute.socket), SocketProxy)
            assert connected_client.extra(INETClientAttribute.remote_address) == client_address
            assert connected_client.extra(INETClientAttribute.local_address) == client.getpeername()

            if use_ssl:
                assert connected_client.extra(TLSAttribute.sslcontext, None) is not None
                assert connected_client.extra(TLSAttribute.peercert, None) is not None

    def test____serve_forever____disable_nagle_algorithm(
        self,
        client_factory: Callable[[], StreamSocket],
        request_handler: MyStreamRequestHandler,
    ) -> None:
        for _ in range(3):
            _ = client_factory()

        assert len(request_handler.connected_clients) == 3
        for connected_client in request_handler.connected_clients.values():
            tcp_nodelay_state: int = connected_client.extra(INETClientAttribute.socket).getsockopt(IPPROTO_TCP, TCP_NODELAY)

            # Do not test with '== 1', on MacOS it will return 4
            # (c.f. https://stackoverflow.com/a/31835137)
            assert tcp_nodelay_state != 0

    def test____serve_forever____shutdown_during_loop____kill_client_tasks(
        self,
        server: MyTCPServer,
        client_factory: Callable[[], StreamSocket],
    ) -> None:
        client = client_factory()

        server.shutdown()
        time.sleep(0.3)

        with contextlib.suppress(ConnectionError):
            assert client.recv(1024) == b""

    def test____serve_forever____partial_request(
        self,
        client_factory: Callable[[], StreamSocket],
        request_handler: MyStreamRequestHandler,
    ) -> None:
        client = client_factory()
        client_address: tuple[Any, ...] = client.getsockname()

        client.send_all(b"hello")
        time.sleep(0.1)

        client.send_all(b", world!\n")

        assert client.readline() == b"HELLO, WORLD!\n"
        assert request_handler.request_received[client_address] == ["hello, world!"]

    def test____serve_forever____several_requests_at_same_time(
        self,
        client_factory: Callable[[], StreamSocket],
        request_handler: MyStreamRequestHandler,
    ) -> None:
        client = client_factory()
        client_address: tuple[Any, ...] = client.getsockname()

        client.send_all(b"hello\nworld\n")

        assert client.readline() == b"HELLO\n"
        assert client.readline() == b"WORLD\n"
        assert request_handler.request_received[client_address] == ["hello", "world"]

    def test____serve_forever____several_requests_at_same_time____close_between(
        self,
        client_factory: Callable[[], StreamSocket],
        request_handler: MyStreamRequestHandler,
    ) -> None:
        client = client_factory()
        client_address: tuple[Any, ...] = client.getsockname()
        request_handler.close_client_after_n_request = 1

        client.send_all(b"hello\nworld\n")

        assert client.readline() == b"HELLO\n"
        assert client.recv(1024) == b""
        assert request_handler.request_received[client_address] == ["hello"]

    def test____serve_forever____save_request_handler_context(
        self,
        client_factory: Callable[[], StreamSocket],
        request_handler: MyStreamRequestHandler,
    ) -> None:
        client = client_factory()
        client_address: tuple[Any, ...] = client.getsockname()

        client.send_all(b"__wait__\nhello, world!\n")

        assert client.readline() == b"After wait: hello, world!\n"
        assert request_handler.request_received[client_address] == ["hello, world!"]

    def test____serve_forever____bad_request(
        self,
        client_factory: Callable[[], StreamSocket],
        request_handler: MyStreamRequestHandler,
    ) -> None:
        client = client_factory()
        client_address: tuple[Any, ...] = client.getsockname()

        client.send_all("\u00e9\n".encode("latin-1"))  # StringSerializer does not accept unicode

        assert client.readline() == b"wrong encoding man.\n"
        assert request_handler.request_received[client_address] == []
        assert isinstance(request_handler.bad_request_received[client_address][0], StreamProtocolParseError)
        assert isinstance(request_handler.bad_request_received[client_address][0].error, IncrementalDeserializeError)

    @pytest.mark.parametrize("socket_family", ["AF_INET"], indirect=True)
    @pytest.mark.parametrize("use_ssl", ["NO_SSL"], indirect=True)
    @pytest.mark.parametrize(
        "request_handler",
        [
            pytest.param(MyStreamRequestHandler, id="during_handle"),
            pytest.param(InitialHandshakeRequestHandler, id="during_on_connection_hook"),
        ],
        indirect=True,
    )
    def test____serve_forever____connection_reset_error(
        self,
        client_factory: Callable[[], StreamSocket],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.WARNING, LOGGER.name)
        client = client_factory()

        enable_socket_linger(client, timeout=0)

        self._wait_client_disconnected(client)

        # ECONNRESET not logged
        assert len(caplog.records) == 0

    @pytest.mark.parametrize("mute_thrown_exception", [False, True], ids=lambda p: f"mute_thrown_exception__{p}")
    @pytest.mark.parametrize("read_on_connection", [False, True], ids=lambda p: f"read_on_connection__{p}")
    @pytest.mark.parametrize("request_handler", [ErrorInRequestHandler], indirect=True)
    @pytest.mark.parametrize(
        "stream_protocol",
        [
            pytest.param("invalid", id="serializer_crash"),
            pytest.param("invalid_buffered", id="buffered_serializer_crash"),
        ],
        indirect=True,
    )
    def test____serve_forever____internal_error(
        self,
        mute_thrown_exception: bool,
        read_on_connection: bool,
        request_handler: ErrorInRequestHandler,
        client_factory: Callable[[], StreamSocket],
        caplog: pytest.LogCaptureFixture,
        logger_crash_maximum_nb_lines: dict[str, int],
    ) -> None:
        caplog.set_level(logging.ERROR, LOGGER.name)
        if not mute_thrown_exception:
            logger_crash_maximum_nb_lines[LOGGER.name] = 3
        request_handler.mute_thrown_exception = mute_thrown_exception
        request_handler.read_on_connection = read_on_connection
        client = client_factory()

        expected_messages = {
            b"RuntimeError: protocol.build_packet_from_buffer() crashed (caused by SystemError: CRASH)\n",
            b"RuntimeError: protocol.build_packet_from_chunks() crashed (caused by SystemError: CRASH)\n",
        }

        client.send_all(b"something\n")

        if mute_thrown_exception:
            assert client.readline() in expected_messages
            client.send_all(b"something\n")
            assert client.readline() in expected_messages
            time.sleep(0.1)
            assert len(caplog.records) == 0  # After two attempts
        else:
            with contextlib.suppress(ConnectionError):
                assert client.readline() in expected_messages
                assert client.recv(1024) == b""
            time.sleep(0.1)
            assert len(caplog.records) == 3
            assert caplog.records[1].exc_info is not None
            assert type(caplog.records[1].exc_info[1]) is RuntimeError

    @pytest.mark.parametrize("excgrp", [False, True], ids=lambda p: f"exception_group_raised__{p}")
    def test____serve_forever____unexpected_error_during_process(
        self,
        excgrp: bool,
        client_factory: Callable[[], StreamSocket],
        caplog: pytest.LogCaptureFixture,
        logger_crash_maximum_nb_lines: dict[str, int],
    ) -> None:
        caplog.set_level(logging.ERROR, LOGGER.name)
        logger_crash_maximum_nb_lines[LOGGER.name] = 3
        client = client_factory()

        client.send_all(b"__error_excgrp__\n" if excgrp else b"__error__\n")
        with contextlib.suppress(ConnectionError):
            assert client.recv(1024) == b""
        time.sleep(0.1)

        assert len(caplog.records) == 3
        assert caplog.records[1].exc_info is not None
        if excgrp:
            assert type(caplog.records[1].exc_info[1]) is ExceptionGroup
            assert type(caplog.records[1].exc_info[1].exceptions[0]) is RandomError
        else:
            assert type(caplog.records[1].exc_info[1]) is RandomError

    @pytest.mark.parametrize("stream_protocol", [pytest.param("bad_serialize", id="serializer_crash")], indirect=True)
    def test____serve_forever____unexpected_error_during_response_serialization(
        self,
        client_factory_no_handshake: Callable[[], StreamSocket],
        caplog: pytest.LogCaptureFixture,
        logger_crash_maximum_nb_lines: dict[str, int],
        request_handler: MyStreamRequestHandler,
    ) -> None:
        request_handler.milk_handshake = False
        caplog.set_level(logging.ERROR, LOGGER.name)
        logger_crash_maximum_nb_lines[LOGGER.name] = 1
        client = client_factory_no_handshake()

        while not request_handler.connected_clients:
            time.sleep(0.1)

        client.send_all(b"request\n")
        assert client.recv(1024) == b""
        time.sleep(0.1)

        assert len(caplog.records) == 1
        assert caplog.records[0].getMessage() == "RuntimeError: protocol.generate_chunks() crashed (caused by SystemError: CRASH)"
        assert caplog.records[0].levelno == logging.ERROR

    def test____serve_forever____os_error(
        self,
        caplog: pytest.LogCaptureFixture,
        logger_crash_maximum_nb_lines: dict[str, int],
        client_factory: Callable[[], StreamSocket],
    ) -> None:
        caplog.set_level(logging.ERROR, LOGGER.name)
        logger_crash_maximum_nb_lines[LOGGER.name] = 3
        client = client_factory()

        client.send_all(b"__os_error__\n")
        with contextlib.suppress(ConnectionError):
            assert client.recv(1024) == b""
        time.sleep(0.1)

        assert len(caplog.records) == 3
        assert caplog.records[1].exc_info is not None
        assert type(caplog.records[1].exc_info[1]) is OSError

    @pytest.mark.parametrize("excgrp", [False, True], ids=lambda p: f"exception_group_raised__{p}")
    def test____serve_forever____use_of_a_closed_client_in_request_handler(
        self,
        excgrp: bool,
        client_factory: Callable[[], StreamSocket],
        caplog: pytest.LogCaptureFixture,
        logger_crash_maximum_nb_lines: dict[str, int],
    ) -> None:
        caplog.set_level(logging.WARNING, LOGGER.name)
        logger_crash_maximum_nb_lines[LOGGER.name] = 1
        client = client_factory()
        host, port = client.getsockname()[:2]

        client.send_all(b"__closed_client_error_excgrp__\n" if excgrp else b"__closed_client_error__\n")
        assert client.recv(1024) == b""
        self._wait_client_disconnected(client)

        assert len(caplog.records) == 1
        assert caplog.records[0].getMessage() == f"There have been attempts to do operation on closed client ({host!r}, {port})"
        assert caplog.records[0].levelno == logging.WARNING

    def test____serve_forever____connection_error_in_request_handler(
        self,
        client_factory: Callable[[], StreamSocket],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.WARNING, LOGGER.name)
        client = client_factory()

        client.send_all(b"__connection_error__\n")
        assert client.recv(1024) == b""
        time.sleep(0.1)

        assert len(caplog.records) == 0

    def test____serve_forever____connection_error_in_disconnect_hook(
        self,
        client_factory: Callable[[], StreamSocket],
        request_handler: MyStreamRequestHandler,
        caplog: pytest.LogCaptureFixture,
        logger_crash_maximum_nb_lines: dict[str, int],
    ) -> None:
        caplog.set_level(logging.WARNING, LOGGER.name)
        logger_crash_maximum_nb_lines[LOGGER.name] = 1
        client = client_factory()
        request_handler.fail_on_disconnection = True

        self._wait_client_disconnected(client)

        # ECONNRESET not logged
        assert len(caplog.records) == 1
        assert caplog.records[0].getMessage() == "ConnectionError raised in request_handler.on_disconnection()"
        assert caplog.records[0].levelno == logging.WARNING

    def test____serve_forever____explicitly_closed_by_request_handler(
        self,
        client_factory: Callable[[], StreamSocket],
    ) -> None:
        client = client_factory()

        client.send_all(b"__close__\n")

        assert client.recv(1024) == b""

    def test____serve_forever____request_handler_ask_to_stop_accepting_new_connections(
        self,
        client_factory: Callable[[], StreamSocket],
        server_thread: threading.Thread,
        server: MyTCPServer,
    ) -> None:
        client = client_factory()

        client.send_all(b"__stop_listening__\n")

        assert client.readline() == b"successfully stop listening\n"
        time.sleep(0.1)

        assert not server.is_serving()

        with pytest.RaisesGroup(ConnectionError):
            client_factory()

        client.close()
        server_thread.join(timeout=5.0)
        assert not server_thread.is_alive()

    def test____serve_forever____close_client_on_connection_hook(
        self,
        client_factory: Callable[[], StreamSocket],
        request_handler: MyStreamRequestHandler,
    ) -> None:
        request_handler.close_all_clients_on_connection = True
        client = client_factory()

        assert client.recv(1024) == b""

    @pytest.mark.parametrize("request_handler", [TimeoutYieldedRequestHandler], indirect=True)
    @pytest.mark.parametrize("request_timeout", [0.0, 1.0], ids=lambda p: f"timeout__{p}")
    @pytest.mark.parametrize("timeout_on_second_yield", [False, True], ids=lambda p: f"timeout_on_second_yield__{p}")
    def test____serve_forever____throw_cancelled_error(
        self,
        request_timeout: float,
        timeout_on_second_yield: bool,
        request_handler: TimeoutYieldedRequestHandler,
        client_factory: Callable[[], StreamSocket],
    ) -> None:
        request_handler.request_timeout = request_timeout
        request_handler.timeout_on_second_yield = timeout_on_second_yield
        client = client_factory()

        if timeout_on_second_yield:
            client.send_all(b"something\n")
            assert client.readline() == b"something\n"

        assert client.readline() == b"successfully timed out\n"

    @pytest.mark.parametrize("request_handler", [ErrorBeforeYieldHandler], indirect=True)
    def test____serve_forever____request_handler_crashed_before_yield(
        self,
        server: MyTCPServer,
        caplog: pytest.LogCaptureFixture,
        logger_crash_maximum_nb_lines: dict[str, int],
        client_factory: Callable[[], StreamSocket],
    ) -> None:
        caplog.set_level(logging.ERROR, LOGGER.name)
        logger_crash_maximum_nb_lines[LOGGER.name] = 3

        with contextlib.suppress(ConnectionError):
            client = client_factory()
            assert client.recv(1024) == b""
        time.sleep(0.1)
        assert len(caplog.records) == 3
        assert caplog.records[1].exc_info is not None
        assert type(caplog.records[1].exc_info[1]) is RandomError

    @pytest.mark.parametrize("request_handler", [RequestRefusedHandler], indirect=True)
    @pytest.mark.parametrize("refuse_after", [0, 5], ids=lambda p: f"refuse_after__{p}")
    def test____serve_forever____request_handler_did_not_yield(
        self,
        refuse_after: int,
        request_handler: RequestRefusedHandler,
        caplog: pytest.LogCaptureFixture,
        client_factory: Callable[[], StreamSocket],
    ) -> None:
        request_handler.refuse_after = refuse_after
        caplog.set_level(logging.ERROR, LOGGER.name)

        with contextlib.suppress(ConnectionError):
            # If refuse after is equal to zero, client_factory() can raise ConnectionResetError
            client = client_factory()

            for _ in range(refuse_after):
                client.send_all(b"something\n")
                assert client.readline() == b"something\n"

            assert client.recv(1024) == b""

        time.sleep(0.1)
        assert len(caplog.records) == 0

    @pytest.mark.parametrize("request_handler", [InitialHandshakeRequestHandler], indirect=True)
    @pytest.mark.parametrize("handshake_2fa", [True, False], ids=lambda p: f"handshake_2fa__{p}")
    def test____serve_forever____request_handler_on_connection_is_async_gen(
        self,
        client_factory: Callable[[], StreamSocket],
        handshake_2fa: bool,
        request_handler: InitialHandshakeRequestHandler,
    ) -> None:
        request_handler.handshake_2fa = handshake_2fa
        client = client_factory()

        client.send_all(b"chocolate\n")
        if handshake_2fa:
            assert client.readline() == b"2FA code needed\n"
            client.send_all(b"42\n")

        assert client.readline() == b"you can enter\n"
        client.send_all(b"something\n")
        assert client.readline() == b"something\n"

    @pytest.mark.parametrize("request_handler", [InitialHandshakeRequestHandler], indirect=True)
    @pytest.mark.parametrize("handshake_2fa", [True, False], ids=lambda p: f"handshake_2fa__{p}")
    def test____serve_forever____request_handler_on_connection_is_async_gen____close_connection(
        self,
        client_factory: Callable[[], StreamSocket],
        handshake_2fa: bool,
        request_handler: InitialHandshakeRequestHandler,
    ) -> None:
        request_handler.handshake_2fa = handshake_2fa
        client = client_factory()

        if handshake_2fa:
            client.send_all(b"chocolate\n")
            assert client.readline() == b"2FA code needed\n"
            client.send_all(b"123\n")
            assert client.readline() == b"wrong code\n"
        else:
            client.send_all(b"something_else\n")
            assert client.readline() == b"wrong password\n"
        assert client.recv(1024) == b""

    @pytest.mark.parametrize("request_handler", [InitialHandshakeRequestHandler], indirect=True)
    @pytest.mark.parametrize("handshake_2fa", [True, False], ids=lambda p: f"handshake_2fa__{p}")
    def test____serve_forever____request_handler_on_connection_is_async_gen____throw_cancel_error_within_generator(
        self,
        client_factory: Callable[[], StreamSocket],
        handshake_2fa: bool,
        request_handler: InitialHandshakeRequestHandler,
    ) -> None:
        request_handler.handshake_2fa = handshake_2fa
        client = client_factory()

        if handshake_2fa:
            client.send_all(b"chocolate\n")
            assert client.readline() == b"2FA code needed\n"

        assert client.readline() == b"timeout error\n"

    @pytest.mark.parametrize("request_handler", [InitialHandshakeRequestHandler], indirect=True)
    def test____serve_forever____request_handler_on_connection_is_async_gen____exit_before_first_yield(
        self,
        request_handler: InitialHandshakeRequestHandler,
        client_factory: Callable[[], StreamSocket],
    ) -> None:
        request_handler.bypass_handshake = True
        client = client_factory()

        client.send_all(b"something_else\n")
        assert client.readline() == b"something_else\n"

    @pytest.mark.parametrize("use_ssl", ["USE_SSL"], indirect=True)
    @pytest.mark.parametrize("ssl_handshake_timeout", [pytest.param(1, id="timeout__1sec")], indirect=True)
    def test____serve_forever____ssl_handshake_timeout_error(
        self,
        server_address: tuple[str, int],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.WARNING, LOGGER.name)

        with StreamSocket.open_tcp_connection(*server_address) as socket:
            with pytest.raises(OSError):
                # The SSL handshake expects the client to send the list of encryption algorithms.
                # But we won't, so the server will close the connection after 1 second
                # and raise a TimeoutError.
                assert socket.recv(256 * 1024) == b""
                # If sock_recv() did not raise, manually trigger the error
                raise ConnectionAbortedError

        time.sleep(0.1)
        assert len(caplog.records) == 0

    @pytest.mark.parametrize("use_ssl", ["USE_SSL"], indirect=True)
    @pytest.mark.parametrize("ssl_handshake_timeout", [pytest.param(1, id="timeout__1sec")], indirect=True)
    @pytest.mark.parametrize("ssl_standard_compatible", [False, True], indirect=True, ids=lambda p: f"standard_compatible__{p}")
    @pytest.mark.parametrize(
        "request_handler",
        [
            pytest.param(MyStreamRequestHandler, id="during_handle"),
            pytest.param(InitialHandshakeRequestHandler, id="during_on_connection_hook"),
        ],
        indirect=True,
    )
    def test____serve_forever____suppress_ssl_ragged_eof_errors(
        self,
        server_address: tuple[str, int],
        server_ssl_context: ssl.SSLContext,
        client_ssl_context: ssl.SSLContext,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.WARNING, LOGGER.name)

        if hasattr(ssl, "OP_IGNORE_UNEXPECTED_EOF"):
            # This test must fail if this option has not been unset when creating the server
            assert (server_ssl_context.options & ssl.OP_IGNORE_UNEXPECTED_EOF) == 0

        sock = StreamSocket.open_tcp_connection(
            *server_address,
            ssl_context=client_ssl_context,
            server_hostname="test.example.com",
            ssl_handshake_timeout=1,
        )
        time.sleep(0.1)
        # Will not do shutdown handshake on close.
        sock.abort()

        time.sleep(0.1)
        assert len(caplog.records) == 0
