from __future__ import annotations

import collections
import contextlib
import logging
import selectors
import threading
import time
from collections.abc import Callable, Generator
from typing import Any

from easynetwork.exceptions import BaseProtocolParseError, ClientClosedError, DatagramProtocolParseError, DeserializeError
from easynetwork.lowlevel._utils import remove_traceback_frames_in_place
from easynetwork.lowlevel.request_handler import RecvParams
from easynetwork.lowlevel.socket import SocketAddress, SocketProxy
from easynetwork.protocol import DatagramProtocol
from easynetwork.servers.handlers import BlockingDatagramClient, BlockingDatagramRequestHandler, INETClientAttribute
from easynetwork.servers.threaded_udp import ThreadedUDPNetworkServer

import pytest

from ..socket import DatagramSocket
from .base import BaseTestThreadedServer


class RandomError(Exception):
    pass


def fetch_client_address(client: BlockingDatagramClient[Any]) -> SocketAddress:
    return client.extra(INETClientAttribute.remote_address)


LOGGER = logging.getLogger(__name__)


class MyDatagramRequestHandler(BlockingDatagramRequestHandler[str, str]):
    request_count: collections.Counter[tuple[Any, ...]]
    request_received: collections.defaultdict[tuple[Any, ...], list[str]]
    bad_request_received: collections.defaultdict[tuple[Any, ...], list[BaseProtocolParseError]]
    created_clients: set[BlockingDatagramClient[str]]
    created_clients_map: dict[tuple[Any, ...], BlockingDatagramClient[str]]
    server: ThreadedUDPNetworkServer[str, str]

    def service_init(self, exit_stack: contextlib.ExitStack, server: ThreadedUDPNetworkServer[str, str]) -> None:
        super().service_init(exit_stack, server)
        self.server = server
        assert isinstance(self.server, ThreadedUDPNetworkServer)

        self.request_count = collections.Counter()
        exit_stack.callback(self.request_count.clear)

        self.request_received = collections.defaultdict(list)
        exit_stack.callback(self.request_received.clear)

        self.bad_request_received = collections.defaultdict(list)
        exit_stack.callback(self.bad_request_received.clear)

        self.created_clients = set()
        self.created_clients_map = dict()
        exit_stack.callback(self.created_clients_map.clear)
        exit_stack.callback(self.created_clients.clear)

        exit_stack.callback(self.service_quit)

    def service_quit(self) -> None:
        # At this point, ALL clients should be closed (since the socket is closed)
        for client in self.created_clients:
            assert client.is_closing()
            with pytest.raises(ClientClosedError):
                client.send_packet("something")

    def handle(self, client: BlockingDatagramClient[str]) -> Generator[None, str]:
        self.created_clients.add(client)
        self.created_clients_map.setdefault(fetch_client_address(client), client)
        request = yield from self.handle_bad_requests(client)
        self.request_count[fetch_client_address(client)] += 1
        match request:
            case "__ping__":
                client.send_packet("pong")
            case "__error__":
                raise RandomError("Sorry man!")
            case "__error_excgrp__":
                raise ExceptionGroup("RandomError", [RandomError("Sorry man!")])
            case "__os_error__":
                raise OSError("Server issue.")
            case "__closed_client_error__":
                raise ClientClosedError
            case "__closed_client_error_excgrp__":
                raise ExceptionGroup("ClientClosedError", [ClientClosedError()])
            case "__eq__":
                try:
                    assert client in list(self.created_clients), "client not in list(self.created_clients)"
                    assert object() not in list(self.created_clients), "object() in list(self.created_clients)"
                except AssertionError as exc:
                    client.send_packet(f"False: {exc}")
                    LOGGER.error("AssertionError", exc_info=exc)
                else:
                    client.send_packet("True")
            case "__cache__":
                stored_client_object = self.created_clients_map[fetch_client_address(client)]
                try:
                    assert client is stored_client_object, "client is not stored_client_object"
                except AssertionError as exc:
                    client.send_packet(f"False: {exc}")
                    LOGGER.error("AssertionError", exc_info=exc)
                else:
                    client.send_packet("True")
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

    def handle_bad_requests(self, client: BlockingDatagramClient[str]) -> Generator[None, str, str]:
        while True:
            try:
                return (yield)
            except DatagramProtocolParseError as exc:
                remove_traceback_frames_in_place(exc, 1)
                self.bad_request_received[fetch_client_address(client)].append(exc)
                client.send_packet("wrong encoding man.")


class TimeoutYieldedRequestHandler(BlockingDatagramRequestHandler[str, str]):
    request_timeout: float = 1.0
    timeout_on_third_yield: bool = False

    def handle(self, client: BlockingDatagramClient[str]) -> Generator[RecvParams | None, str]:
        assert (yield None) == "something"
        if self.timeout_on_third_yield:
            request = yield None
            client.send_packet(request)
        try:
            with pytest.raises(TimeoutError):
                yield RecvParams(timeout=self.request_timeout)
            client.send_packet("successfully timed out")
        except BaseException:
            client.send_packet("error occurred")
            raise
        finally:
            self.request_timeout = 1.0  # Force reset to 1 second in order not to overload the server


class ConcurrencyTestRequestHandler(BlockingDatagramRequestHandler[str, str]):
    sleep_time_before_second_yield: float | None = None
    sleep_time_before_response: float | None = None
    recreate_generator: bool = True

    def handle(self, client: BlockingDatagramClient[str]) -> Generator[None, str]:
        while True:
            assert (yield) == "something"
            if self.sleep_time_before_second_yield is not None:
                time.sleep(self.sleep_time_before_second_yield)
            request = yield
            if self.sleep_time_before_response is not None:
                time.sleep(self.sleep_time_before_response)
            client.send_packet(f"After wait: {request}")
            if self.recreate_generator:
                break


class RequestRefusedHandler(BlockingDatagramRequestHandler[str, str]):
    refuse_after: int = 2**64
    bypass_refusal: bool = False

    def service_init(self, exit_stack: contextlib.ExitStack, server: Any) -> None:
        self.request_count: collections.Counter[BlockingDatagramClient[str]] = collections.Counter()
        exit_stack.callback(self.request_count.clear)

    def handle(self, client: BlockingDatagramClient[str]) -> Generator[None, str]:
        if self.request_count[client] >= self.refuse_after and not self.bypass_refusal:
            return
        request = yield
        self.request_count[client] += 1
        client.send_packet(request)


class ErrorInRequestHandler(BlockingDatagramRequestHandler[str, str]):
    mute_thrown_exception: bool = False

    def handle(self, client: BlockingDatagramClient[str]) -> Generator[None, str]:
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


class ErrorBeforeYieldHandler(BlockingDatagramRequestHandler[str, str]):
    raise_error: bool = False

    def handle(self, client: BlockingDatagramClient[str]) -> Generator[None, str]:
        if self.raise_error:
            raise RandomError("An error occurred")
        request = yield
        client.send_packet(request)


class MyUDPServer(ThreadedUDPNetworkServer[str, str]):
    __slots__ = ()


@pytest.mark.flaky(retries=3, delay=0.1)
class TestThreadedUDPNetworkServer(BaseTestThreadedServer):
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
    def request_handler(request: pytest.FixtureRequest) -> BlockingDatagramRequestHandler[str, str]:
        request_handler_cls: type[BlockingDatagramRequestHandler[str, str]] = getattr(request, "param", MyDatagramRequestHandler)
        return request_handler_cls()

    @pytest.fixture
    @staticmethod
    def server_not_activated(
        request_handler: BlockingDatagramRequestHandler[str, str],
        localhost_ip: str,
        datagram_protocol: DatagramProtocol[str, str],
    ) -> Generator[MyUDPServer]:
        server = MyUDPServer(
            localhost_ip,
            0,
            datagram_protocol,
            request_handler,
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
        request_handler: BlockingDatagramRequestHandler[str, str],
        localhost_ip: str,
        datagram_protocol: DatagramProtocol[str, str],
    ) -> Generator[MyUDPServer]:
        with MyUDPServer(
            localhost_ip,
            0,
            datagram_protocol,
            request_handler,
            selector_factory=selector_factory,
            logger=LOGGER,
        ) as server:
            assert server.is_listening()
            assert server.get_sockets()
            assert server.get_addresses()
            yield server

    @pytest.fixture
    @staticmethod
    def server_address(run_server: threading.Event, server: MyUDPServer) -> tuple[str, int]:
        if not run_server.wait(timeout=1.0):
            raise TimeoutError("run_server")
        assert server.is_serving()
        server_addresses = server.get_addresses()
        assert len(server_addresses) == 1
        return server_addresses[0].for_connection()

    @pytest.fixture
    @staticmethod
    def client_factory(
        server_address: tuple[str, int],
        socket_family: int,
        localhost_ip: str,
    ) -> Generator[Callable[[], DatagramSocket]]:
        with contextlib.ExitStack() as stack:

            def factory() -> DatagramSocket:
                endpoint = DatagramSocket.open_udp_connection(
                    *server_address,
                    local_address=(localhost_ip, 0),
                    family=socket_family,
                )
                stack.enter_context(endpoint)
                endpoint.set_timeout(10.0)
                return endpoint

            yield factory

    @staticmethod
    def __ping_server(endpoint: DatagramSocket) -> None:
        endpoint.sendto(b"__ping__", None)
        pong, _ = endpoint.recvfrom(timeout=1.0)
        assert pong == b"pong"

    def test____serve_forever____server_assignment(
        self,
        server: MyUDPServer,
        run_server: threading.Event,
        request_handler: MyDatagramRequestHandler,
    ) -> None:
        run_server.wait()
        assert request_handler.server == server

    def test____serve_forever____handle_request(
        self,
        client_factory: Callable[[], DatagramSocket],
        request_handler: MyDatagramRequestHandler,
    ) -> None:
        endpoint = client_factory()
        client_address: tuple[Any, ...] = endpoint.getsockname()

        endpoint.sendto(b"hello, world.", None)
        assert (endpoint.recvfrom())[0] == b"HELLO, WORLD."

        assert request_handler.request_received[client_address] == ["hello, world."]

    def test____serve_forever____client_extra_attributes(
        self,
        client_factory: Callable[[], DatagramSocket],
        request_handler: MyDatagramRequestHandler,
    ) -> None:
        all_endpoints: list[DatagramSocket] = [client_factory() for _ in range(3)]

        for endpoint in all_endpoints:
            self.__ping_server(endpoint)

        assert len(request_handler.created_clients_map) == 3

        for endpoint in all_endpoints:
            client_address: tuple[Any, ...] = endpoint.getsockname()
            connected_client: BlockingDatagramClient[str] = request_handler.created_clients_map[client_address]

            assert isinstance(connected_client.extra(INETClientAttribute.socket), SocketProxy)
            assert connected_client.extra(INETClientAttribute.remote_address) == client_address
            assert connected_client.extra(INETClientAttribute.local_address) == endpoint.getpeername()

    def test____serve_forever____client_equality(
        self,
        client_factory: Callable[[], DatagramSocket],
    ) -> None:
        for _ in range(3):
            endpoint = client_factory()

            endpoint.sendto(b"__eq__", None)
            assert (endpoint.recvfrom())[0] == b"True"

    def test____serve_forever____client_cache(
        self,
        client_factory: Callable[[], DatagramSocket],
    ) -> None:
        for _ in range(3):
            endpoint = client_factory()

            self.__ping_server(endpoint)

            endpoint.sendto(b"__cache__", None)
            assert (endpoint.recvfrom())[0] == b"True"

    def test____serve_forever____save_request_handler_context(
        self,
        client_factory: Callable[[], DatagramSocket],
        request_handler: MyDatagramRequestHandler,
    ) -> None:
        endpoint = client_factory()
        client_address: tuple[Any, ...] = endpoint.getsockname()

        endpoint.sendto(b"__wait__", None)
        endpoint.sendto(b"hello, world.", None)
        assert (endpoint.recvfrom(timeout=1.0))[0] == b"After wait: hello, world."

        assert request_handler.request_received[client_address] == ["hello, world."]

    def test____serve_forever____save_request_handler_context____extra_datagram_are_rescheduled(
        self,
        client_factory: Callable[[], DatagramSocket],
        request_handler: MyDatagramRequestHandler,
    ) -> None:
        endpoint = client_factory()
        client_address: tuple[Any, ...] = endpoint.getsockname()

        endpoint.sendto(b"__wait__", None)
        endpoint.sendto(b"hello, world.", None)
        endpoint.sendto(b"Test 2.", None)
        assert (endpoint.recvfrom(timeout=1.0))[0] == b"After wait: hello, world."
        assert (endpoint.recvfrom(timeout=1.0))[0] == b"TEST 2."

        assert set(request_handler.request_received[client_address]) == {"hello, world.", "Test 2."}

    def test____serve_forever____save_request_handler_context____server_shutdown(
        self,
        server: MyUDPServer,
        client_factory: Callable[[], DatagramSocket],
        request_handler: MyDatagramRequestHandler,
    ) -> None:
        endpoint = client_factory()
        client_address: tuple[Any, ...] = endpoint.getsockname()

        endpoint.sendto(b"__wait__", None)
        for _ in range(10):
            if client_address in request_handler.created_clients_map:
                break
            time.sleep(0.1)
        else:
            raise TimeoutError

        server.shutdown(timeout=1.0)

    def test____serve_forever____bad_request(
        self,
        client_factory: Callable[[], DatagramSocket],
        request_handler: MyDatagramRequestHandler,
    ) -> None:
        endpoint = client_factory()
        client_address: tuple[Any, ...] = endpoint.getsockname()

        endpoint.sendto("\u00e9".encode("latin-1"), None)  # StringSerializer does not accept unicode
        time.sleep(0.1)

        assert (endpoint.recvfrom())[0] == b"wrong encoding man."

        assert request_handler.request_received[client_address] == []
        assert isinstance(request_handler.bad_request_received[client_address][0], DatagramProtocolParseError)
        assert isinstance(request_handler.bad_request_received[client_address][0].error, DeserializeError)

    @pytest.mark.parametrize("mute_thrown_exception", [False, True])
    @pytest.mark.parametrize("request_handler", [ErrorInRequestHandler], indirect=True)
    @pytest.mark.parametrize("datagram_protocol", [pytest.param("invalid", id="serializer_crash")], indirect=True)
    def test____serve_forever____internal_error(
        self,
        mute_thrown_exception: bool,
        request_handler: ErrorInRequestHandler,
        client_factory: Callable[[], DatagramSocket],
        caplog: pytest.LogCaptureFixture,
        logger_crash_maximum_nb_lines: dict[str, int],
    ) -> None:
        caplog.set_level(logging.ERROR, LOGGER.name)
        if not mute_thrown_exception:
            logger_crash_maximum_nb_lines[LOGGER.name] = 3
        request_handler.mute_thrown_exception = mute_thrown_exception
        endpoint = client_factory()

        expected_message = b"RuntimeError: protocol.build_packet_from_datagram() crashed (caused by SystemError: CRASH)"

        endpoint.sendto(b"something", None)
        time.sleep(0.2)

        assert (endpoint.recvfrom())[0] == expected_message
        if mute_thrown_exception:
            endpoint.sendto(b"something", None)
            time.sleep(0.2)
            assert (endpoint.recvfrom())[0] == expected_message
            assert len(caplog.records) == 0  # After two attempts
        else:
            assert len(caplog.records) == 3
            assert caplog.records[1].exc_info is not None
            assert type(caplog.records[1].exc_info[1]) is RuntimeError

    @pytest.mark.parametrize("excgrp", [False, True], ids=lambda p: f"exception_group_raised__{p}")
    def test____serve_forever____unexpected_error_during_process(
        self,
        excgrp: bool,
        client_factory: Callable[[], DatagramSocket],
        caplog: pytest.LogCaptureFixture,
        logger_crash_maximum_nb_lines: dict[str, int],
    ) -> None:
        caplog.set_level(logging.ERROR, LOGGER.name)
        logger_crash_maximum_nb_lines[LOGGER.name] = 3
        endpoint = client_factory()

        if excgrp:
            endpoint.sendto(b"__error_excgrp__", None)
        else:
            endpoint.sendto(b"__error__", None)
        time.sleep(0.2)

        assert len(caplog.records) == 3
        assert caplog.records[1].exc_info is not None
        if excgrp:
            assert type(caplog.records[1].exc_info[1]) is ExceptionGroup
            assert type(caplog.records[1].exc_info[1].exceptions[0]) is RandomError
        else:
            assert type(caplog.records[1].exc_info[1]) is RandomError

    @pytest.mark.parametrize("datagram_protocol", [pytest.param("bad_serialize", id="serializer_crash")], indirect=True)
    def test____serve_forever____unexpected_error_during_response_serialization(
        self,
        client_factory: Callable[[], DatagramSocket],
        caplog: pytest.LogCaptureFixture,
        logger_crash_maximum_nb_lines: dict[str, int],
    ) -> None:
        caplog.set_level(logging.ERROR, LOGGER.name)
        logger_crash_maximum_nb_lines[LOGGER.name] = 1
        endpoint = client_factory()

        endpoint.sendto(b"request", None)
        time.sleep(0.2)

        assert len(caplog.records) == 1
        assert caplog.records[0].getMessage() == "RuntimeError: protocol.make_datagram() crashed (caused by SystemError: CRASH)"
        assert caplog.records[0].levelno == logging.ERROR

    def test____serve_forever____os_error(
        self,
        client_factory: Callable[[], DatagramSocket],
        caplog: pytest.LogCaptureFixture,
        logger_crash_maximum_nb_lines: dict[str, int],
    ) -> None:
        caplog.set_level(logging.ERROR, LOGGER.name)
        logger_crash_maximum_nb_lines[LOGGER.name] = 3
        endpoint = client_factory()

        endpoint.sendto(b"__os_error__", None)
        time.sleep(0.2)

        assert len(caplog.records) == 3
        assert caplog.records[1].exc_info is not None
        assert type(caplog.records[1].exc_info[1]) is OSError

    @pytest.mark.parametrize("excgrp", [False, True], ids=lambda p: f"exception_group_raised__{p}")
    def test____serve_forever____use_of_a_closed_client_in_request_handler(  # In a world where this thing happen
        self,
        excgrp: bool,
        client_factory: Callable[[], DatagramSocket],
        caplog: pytest.LogCaptureFixture,
        logger_crash_maximum_nb_lines: dict[str, int],
    ) -> None:
        caplog.set_level(logging.WARNING, LOGGER.name)
        logger_crash_maximum_nb_lines[LOGGER.name] = 1
        endpoint = client_factory()
        host, port = endpoint.getsockname()[:2]

        if excgrp:
            endpoint.sendto(b"__closed_client_error_excgrp__", None)
        else:
            endpoint.sendto(b"__closed_client_error__", None)
        time.sleep(0.2)

        assert len(caplog.records) == 1
        assert caplog.records[0].getMessage() == f"There have been attempts to do operation on closed client ({host!r}, {port})"
        assert caplog.records[0].levelno == logging.WARNING

    @pytest.mark.parametrize("request_handler", [TimeoutYieldedRequestHandler], indirect=True)
    @pytest.mark.parametrize("request_timeout", [0.0, 1.0], ids=lambda p: f"timeout__{p}")
    @pytest.mark.parametrize("timeout_on_third_yield", [False, True], ids=lambda p: f"timeout_on_third_yield__{p}")
    def test____serve_forever____throw_cancelled_error(
        self,
        request_timeout: float,
        timeout_on_third_yield: bool,
        request_handler: TimeoutYieldedRequestHandler,
        client_factory: Callable[[], DatagramSocket],
    ) -> None:
        request_handler.request_timeout = request_timeout
        request_handler.timeout_on_third_yield = timeout_on_third_yield
        endpoint = client_factory()

        endpoint.sendto(b"something", None)
        if timeout_on_third_yield:
            endpoint.sendto(b"something", None)
            assert (endpoint.recvfrom(timeout=request_timeout + 1))[0] == b"something"
        assert (endpoint.recvfrom(timeout=request_timeout + 1))[0] == b"successfully timed out"

    @pytest.mark.parametrize("request_handler", [ErrorBeforeYieldHandler], indirect=True)
    def test____serve_forever____request_handler_crashed_before_yield(
        self,
        request_handler: ErrorBeforeYieldHandler,
        caplog: pytest.LogCaptureFixture,
        logger_crash_maximum_nb_lines: dict[str, int],
        client_factory: Callable[[], DatagramSocket],
    ) -> None:
        caplog.set_level(logging.ERROR, LOGGER.name)
        logger_crash_maximum_nb_lines[LOGGER.name] = 3
        endpoint = client_factory()

        request_handler.raise_error = True
        endpoint.sendto(b"something", None)
        with pytest.raises(TimeoutError):
            endpoint.recvfrom(timeout=0.5)
        assert len(caplog.records) == 3
        assert caplog.records[1].exc_info is not None
        assert type(caplog.records[1].exc_info[1]) is RandomError
        request_handler.raise_error = False
        endpoint.sendto(b"hello world", None)
        assert (endpoint.recvfrom())[0] == b"hello world"

    @pytest.mark.parametrize("request_handler", [RequestRefusedHandler], indirect=True)
    @pytest.mark.parametrize("refuse_after", [0, 5], ids=lambda p: f"refuse_after__{p}")
    def test____serve_forever____request_handler_did_not_yield(
        self,
        refuse_after: int,
        request_handler: RequestRefusedHandler,
        caplog: pytest.LogCaptureFixture,
        client_factory: Callable[[], DatagramSocket],
    ) -> None:
        request_handler.bypass_refusal = False
        request_handler.refuse_after = refuse_after
        caplog.set_level(logging.ERROR, LOGGER.name)
        endpoint = client_factory()

        for _ in range(refuse_after):
            endpoint.sendto(b"a", None)
            assert (endpoint.recvfrom())[0] == b"a"

        endpoint.sendto(b"something", None)
        with pytest.raises(TimeoutError):
            endpoint.recvfrom(timeout=0.5)
        assert len(caplog.records) == 0
        request_handler.bypass_refusal = True
        endpoint.sendto(b"hello world", None)
        assert (endpoint.recvfrom())[0] == b"hello world"

    @pytest.mark.parametrize("request_handler", [ConcurrencyTestRequestHandler], indirect=True)
    def test____serve_forever____datagram_while_request_handle_is_performed(
        self,
        request_handler: ConcurrencyTestRequestHandler,
        client_factory: Callable[[], DatagramSocket],
    ) -> None:
        request_handler.sleep_time_before_second_yield = 0.5
        endpoint = client_factory()

        endpoint.sendto(b"something", None)
        endpoint.sendto(b"hello, world.", None)
        assert (endpoint.recvfrom())[0] == b"After wait: hello, world."

    @pytest.mark.parametrize("request_handler", [ConcurrencyTestRequestHandler], indirect=True)
    @pytest.mark.parametrize("recreate_generator", [False, True], ids=lambda p: f"recreate_generator__{p}")
    def test____serve_forever____too_many_datagrams_while_request_handle_is_performed(
        self,
        recreate_generator: bool,
        request_handler: ConcurrencyTestRequestHandler,
        client_factory: Callable[[], DatagramSocket],
    ) -> None:
        request_handler.sleep_time_before_response = 0.5
        request_handler.recreate_generator = recreate_generator
        endpoint = client_factory()

        endpoint.sendto(b"something", None)
        time.sleep(0.1)
        endpoint.sendto(b"hello, world.", None)
        for i in range(3):
            endpoint.sendto(b"something", None)
            endpoint.sendto(f"hello, world {i+2} times.".encode(), None)
        endpoint.sendto(b"something", None)
        time.sleep(0.1)
        request_handler.sleep_time_before_response = None
        endpoint.sendto(b"hello, world. new game +", None)
        assert (endpoint.recvfrom())[0] == b"After wait: hello, world."
        assert (endpoint.recvfrom())[0] == b"After wait: hello, world 2 times."
        assert (endpoint.recvfrom())[0] == b"After wait: hello, world 3 times."
        assert (endpoint.recvfrom())[0] == b"After wait: hello, world 4 times."
        assert (endpoint.recvfrom())[0] == b"After wait: hello, world. new game +"
