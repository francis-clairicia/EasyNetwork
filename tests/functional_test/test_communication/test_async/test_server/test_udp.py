from __future__ import annotations

import asyncio
import collections
import contextlib
import logging
import weakref
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Sequence
from typing import Any

from easynetwork.api_async.server.handler import AsyncDatagramClient, AsyncDatagramRequestHandler, INETClientAttribute
from easynetwork.api_async.server.udp import AsyncUDPNetworkServer
from easynetwork.exceptions import BaseProtocolParseError, ClientClosedError, DatagramProtocolParseError, DeserializeError
from easynetwork.lowlevel.socket import SocketAddress
from easynetwork.lowlevel.std_asyncio.backend import AsyncIOBackend
from easynetwork.lowlevel.std_asyncio.datagram.endpoint import DatagramEndpoint, create_datagram_endpoint
from easynetwork.lowlevel.std_asyncio.datagram.listener import (
    AsyncioTransportDatagramListenerSocketAdapter,
    RawDatagramListenerSocketAdapter,
)
from easynetwork.protocol import DatagramProtocol

import pytest
import pytest_asyncio

from .....pytest_plugins.asyncio_event_loop import EventLoop
from .base import BaseTestAsyncServer


class NoListenerErrorBackend(AsyncIOBackend):
    async def create_udp_listeners(
        self,
        host: str | Sequence[str] | None,
        port: int,
        *,
        reuse_port: bool = False,
    ) -> Sequence[RawDatagramListenerSocketAdapter] | Sequence[AsyncioTransportDatagramListenerSocketAdapter]:
        return []


class RandomError(Exception):
    pass


def client_address(client: AsyncDatagramClient[Any]) -> SocketAddress:
    return client.extra(INETClientAttribute.remote_address)


class MyAsyncUDPRequestHandler(AsyncDatagramRequestHandler[str, str]):
    request_received: collections.defaultdict[tuple[Any, ...], list[str]]
    bad_request_received: collections.defaultdict[tuple[Any, ...], list[BaseProtocolParseError]]
    created_clients: set[AsyncDatagramClient[str]]
    server: AsyncUDPNetworkServer[str, str]

    async def service_init(self, exit_stack: contextlib.AsyncExitStack, server: AsyncUDPNetworkServer[str, str]) -> None:
        await super().service_init(exit_stack, server)
        self.server = server
        self.request_received = collections.defaultdict(list)
        self.bad_request_received = collections.defaultdict(list)
        self.created_clients = set()

        exit_stack.push_async_callback(self.service_quit)

    async def service_quit(self) -> None:
        # At this point, ALL clients should be closed (since the UDP socket is closed)
        for client in self.created_clients:
            assert client.is_closing()
            with pytest.raises(ClientClosedError):
                await client.send_packet("something")

        del (
            self.request_received,
            self.bad_request_received,
            self.created_clients,
        )

    async def handle(self, client: AsyncDatagramClient[str]) -> AsyncGenerator[None, str]:
        self.created_clients.add(client)
        while True:
            async with self.handle_bad_requests(client):
                request = yield
                break
        match request:
            case "__error__":
                raise RandomError("Sorry man!")
            case "__os_error__":
                raise OSError("Server issue.")
            case "__closed_client_error__":
                raise ClientClosedError
            case "__eq__":
                assert client in list(self.created_clients)
                assert object() not in list(self.created_clients)
                await client.send_packet("True")
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

    @contextlib.asynccontextmanager
    async def handle_bad_requests(self, client: AsyncDatagramClient[str]) -> AsyncIterator[None]:
        try:
            yield
        except DatagramProtocolParseError as exc:
            self.bad_request_received[client_address(client)].append(exc)
            await client.send_packet("wrong encoding man.")


class TimeoutRequestHandler(AsyncDatagramRequestHandler[str, str]):
    request_timeout: float = 1.0

    async def handle(self, client: AsyncDatagramClient[str]) -> AsyncGenerator[None, str]:
        assert (yield) == "something"
        try:
            with pytest.raises(TimeoutError):
                async with asyncio.timeout(self.request_timeout):
                    yield
            await client.send_packet("successfully timed out")
        except BaseException:
            await client.send_packet("error occurred")
            raise
        finally:
            self.request_timeout = 1.0  # Force reset to 1 second in order not to overload the server


class ConcurrencyTestRequestHandler(AsyncDatagramRequestHandler[str, str]):
    sleep_time_before_second_yield: float = 0.0
    sleep_time_before_response: float = 0.0

    async def handle(self, client: AsyncDatagramClient[str]) -> AsyncGenerator[None, str]:
        assert (yield) == "something"
        await asyncio.sleep(self.sleep_time_before_second_yield)
        request = yield
        await asyncio.sleep(self.sleep_time_before_response)
        await client.send_packet(f"After wait: {request}")


class CancellationRequestHandler(AsyncDatagramRequestHandler[str, str]):
    async def handle(self, client: AsyncDatagramClient[str]) -> AsyncGenerator[None, str]:
        yield
        await client.send_packet("response")
        raise asyncio.CancelledError()


class RequestRefusedHandler(AsyncDatagramRequestHandler[str, str]):
    refuse_after: int = 2**64
    bypass_refusal: bool = False

    async def service_init(self, exit_stack: contextlib.AsyncExitStack, server: AsyncUDPNetworkServer[str, str]) -> None:
        self.request_count: collections.Counter[AsyncDatagramClient[str]] = collections.Counter()

    async def handle(self, client: AsyncDatagramClient[str]) -> AsyncGenerator[None, str]:
        if self.request_count[client] >= self.refuse_after and not self.bypass_refusal:
            return
        request = yield
        self.request_count[client] += 1
        await client.send_packet(request)


class ErrorInRequestHandler(AsyncDatagramRequestHandler[str, str]):
    mute_thrown_exception: bool = False

    async def handle(self, client: AsyncDatagramClient[str]) -> AsyncGenerator[None, str]:
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


class ErrorBeforeYieldHandler(AsyncDatagramRequestHandler[str, str]):
    raise_error: bool = False

    async def handle(self, client: AsyncDatagramClient[str]) -> AsyncGenerator[None, str]:
        if self.raise_error:
            raise RandomError("An error occurred")
        request = yield
        await client.send_packet(request)

    async def bad_request(self, client: AsyncDatagramClient[str], exc: BaseProtocolParseError, /) -> None:
        pass


class MyAsyncUDPServer(AsyncUDPNetworkServer[str, str]):
    __slots__ = ()


@pytest.mark.asyncio
class TestAsyncUDPNetworkServer(BaseTestAsyncServer):
    @pytest.fixture
    @staticmethod
    def backend_kwargs(event_loop_name: EventLoop, use_asyncio_transport: bool) -> dict[str, Any]:
        if not use_asyncio_transport:
            if event_loop_name == EventLoop.UVLOOP:
                pytest.xfail("uvloop runner does not implement the needed functions")
        return {"transport": use_asyncio_transport}

    @pytest.fixture
    @staticmethod
    def request_handler(request: Any) -> AsyncDatagramRequestHandler[str, str]:
        request_handler_cls: type[AsyncDatagramRequestHandler[str, str]] = getattr(request, "param", MyAsyncUDPRequestHandler)
        return request_handler_cls()

    @pytest_asyncio.fixture
    @staticmethod
    async def server(
        request_handler: AsyncDatagramRequestHandler[str, str],
        localhost_ip: str,
        datagram_protocol: DatagramProtocol[str, str],
        backend_kwargs: dict[str, Any],
    ) -> AsyncIterator[MyAsyncUDPServer]:
        async with MyAsyncUDPServer(
            localhost_ip,
            0,
            datagram_protocol,
            request_handler,
            backend_kwargs=backend_kwargs,
        ) as server:
            assert not server.sockets
            assert not server.get_addresses()
            yield server

    @pytest_asyncio.fixture
    @staticmethod
    async def server_address(run_server: asyncio.Event, server: MyAsyncUDPServer) -> tuple[str, int]:
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
        socket_family: int,
        localhost_ip: str,
    ) -> AsyncIterator[Callable[[], Awaitable[DatagramEndpoint]]]:
        async with contextlib.AsyncExitStack() as stack:

            async def factory() -> DatagramEndpoint:
                endpoint = await create_datagram_endpoint(
                    family=socket_family,
                    local_addr=(localhost_ip, 0),
                    remote_addr=server_address,
                )
                stack.push_async_callback(endpoint.aclose)
                return endpoint

            yield factory

    async def test____serve_forever____empty_listener_list(
        self,
        request_handler: MyAsyncUDPRequestHandler,
        datagram_protocol: DatagramProtocol[str, str],
    ) -> None:
        async with MyAsyncUDPServer(None, 0, datagram_protocol, request_handler, backend=NoListenerErrorBackend()) as s:
            with pytest.raises(OSError, match=r"^empty listeners list$"):
                await s.serve_forever()

            assert not s.sockets

    @pytest.mark.usefixtures("run_server_and_wait")
    async def test____serve_forever____server_assignment(
        self,
        server: MyAsyncUDPServer,
        request_handler: MyAsyncUDPRequestHandler,
    ) -> None:
        assert request_handler.server == server
        assert isinstance(request_handler.server, AsyncUDPNetworkServer)
        assert isinstance(request_handler.server, weakref.ProxyType)

    async def test____serve_forever____handle_request(
        self,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
        request_handler: MyAsyncUDPRequestHandler,
    ) -> None:
        endpoint = await client_factory()
        client_address: tuple[Any, ...] = endpoint.get_extra_info("sockname")

        await endpoint.sendto(b"hello, world.", None)
        async with asyncio.timeout(3):
            assert (await endpoint.recvfrom())[0] == b"HELLO, WORLD."

        assert request_handler.request_received[client_address] == ["hello, world."]

    async def test____serve_forever____client_equality(
        self,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
    ) -> None:
        for _ in range(3):
            endpoint = await client_factory()

            await endpoint.sendto(b"__eq__", None)
            assert (await endpoint.recvfrom())[0] == b"True"

    async def test____serve_forever____save_request_handler_context(
        self,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
        request_handler: MyAsyncUDPRequestHandler,
    ) -> None:
        endpoint = await client_factory()
        client_address: tuple[Any, ...] = endpoint.get_extra_info("sockname")

        await endpoint.sendto(b"__wait__", None)
        await endpoint.sendto(b"hello, world.", None)
        assert (await endpoint.recvfrom())[0] == b"After wait: hello, world."

        assert request_handler.request_received[client_address] == ["hello, world."]

    async def test____serve_forever____save_request_handler_context____extra_datagram_are_rescheduled(
        self,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
        request_handler: MyAsyncUDPRequestHandler,
    ) -> None:
        endpoint = await client_factory()
        client_address: tuple[Any, ...] = endpoint.get_extra_info("sockname")

        await endpoint.sendto(b"__wait__", None)
        await endpoint.sendto(b"hello, world.", None)
        await endpoint.sendto(b"Test 2.", None)
        assert (await endpoint.recvfrom())[0] == b"After wait: hello, world."

        assert set(request_handler.request_received[client_address]) == {"hello, world.", "Test 2."}

    async def test____serve_forever____bad_request(
        self,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
        request_handler: MyAsyncUDPRequestHandler,
    ) -> None:
        endpoint = await client_factory()
        client_address: tuple[Any, ...] = endpoint.get_extra_info("sockname")

        await endpoint.sendto("\u00E9".encode("latin-1"), None)  # StringSerializer does not accept unicode
        await asyncio.sleep(0.1)

        assert (await endpoint.recvfrom())[0] == b"wrong encoding man."
        assert request_handler.request_received[client_address] == []
        assert isinstance(request_handler.bad_request_received[client_address][0], DatagramProtocolParseError)
        assert isinstance(request_handler.bad_request_received[client_address][0].error, DeserializeError)

    @pytest.mark.parametrize("mute_thrown_exception", [False, True])
    @pytest.mark.parametrize("request_handler", [ErrorInRequestHandler], indirect=True)
    @pytest.mark.parametrize("one_shot_serializer", [pytest.param("invalid", id="serializer_crash")], indirect=True)
    async def test____serve_forever____internal_error(
        self,
        mute_thrown_exception: bool,
        request_handler: ErrorInRequestHandler,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
        caplog: pytest.LogCaptureFixture,
        server: MyAsyncUDPServer,
    ) -> None:
        caplog.set_level(logging.ERROR, server.logger.name)
        request_handler.mute_thrown_exception = mute_thrown_exception
        endpoint = await client_factory()

        expected_message = b"RuntimeError: protocol.build_packet_from_datagram() crashed (caused by SystemError: CRASH)"

        await endpoint.sendto(b"something", None)
        await asyncio.sleep(0.2)

        assert (await endpoint.recvfrom())[0] == expected_message
        if mute_thrown_exception:
            await endpoint.sendto(b"something", None)
            await asyncio.sleep(0.2)
            assert (await endpoint.recvfrom())[0] == expected_message
            assert len(caplog.records) == 0  # After two attempts
        else:
            assert len(caplog.records) == 3

    async def test____serve_forever____unexpected_error_during_process(
        self,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
        caplog: pytest.LogCaptureFixture,
        server: MyAsyncUDPServer,
    ) -> None:
        caplog.set_level(logging.ERROR, server.logger.name)
        endpoint = await client_factory()

        await endpoint.sendto(b"__error__", None)
        await asyncio.sleep(0.2)

        assert len(caplog.records) == 3

    @pytest.mark.parametrize("one_shot_serializer", [pytest.param("bad_serialize", id="serializer_crash")], indirect=True)
    async def test____serve_forever____unexpected_error_during_response_serialization(
        self,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
        caplog: pytest.LogCaptureFixture,
        server: MyAsyncUDPServer,
    ) -> None:
        caplog.set_level(logging.ERROR, server.logger.name)
        endpoint = await client_factory()

        await endpoint.sendto(b"request", None)
        while not caplog.records:
            await asyncio.sleep(0.2)

        assert len(caplog.records) == 1
        assert caplog.records[0].levelno == logging.ERROR
        assert caplog.records[0].message == "RuntimeError: protocol.make_datagram() crashed (caused by SystemError: CRASH)"

    async def test____serve_forever____os_error(
        self,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
        caplog: pytest.LogCaptureFixture,
        server: MyAsyncUDPServer,
    ) -> None:
        caplog.set_level(logging.ERROR, server.logger.name)
        endpoint = await client_factory()

        await endpoint.sendto(b"__os_error__", None)
        await asyncio.sleep(0.2)

        assert len(caplog.records) == 3

    async def test____serve_forever____use_of_a_closed_client_in_request_handler(  # In a world where this thing happen
        self,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
        caplog: pytest.LogCaptureFixture,
        server: MyAsyncUDPServer,
    ) -> None:
        caplog.set_level(logging.WARNING, server.logger.name)
        endpoint = await client_factory()
        host, port = endpoint.get_extra_info("sockname")[:2]

        await endpoint.sendto(b"__closed_client_error__", None)
        await asyncio.sleep(0.2)

        assert len(caplog.records) == 1
        assert caplog.records[0].levelno == logging.WARNING
        assert caplog.records[0].message == f"There have been attempts to do operation on closed client ({host!r}, {port})"

    @pytest.mark.parametrize("request_handler", [TimeoutRequestHandler], indirect=True)
    @pytest.mark.parametrize("request_timeout", [0.0, 1.0], ids=lambda p: f"timeout=={p}")
    async def test____serve_forever____throw_cancelled_error(
        self,
        request_timeout: float,
        request_handler: TimeoutRequestHandler,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
    ) -> None:
        request_handler.request_timeout = request_timeout
        endpoint = await client_factory()

        await endpoint.sendto(b"something", None)
        async with asyncio.timeout(request_timeout + 1):
            assert (await endpoint.recvfrom())[0] == b"successfully timed out"

    @pytest.mark.parametrize("request_handler", [CancellationRequestHandler], indirect=True)
    async def test____serve_forever____request_handler_is_cancelled(
        self,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
    ) -> None:
        endpoint = await client_factory()

        await endpoint.sendto(b"something", None)
        assert (await endpoint.recvfrom())[0] == b"response"

    @pytest.mark.parametrize("request_handler", [ErrorBeforeYieldHandler], indirect=True)
    async def test____serve_forever____request_handler_crashed_before_yield(
        self,
        request_handler: ErrorBeforeYieldHandler,
        caplog: pytest.LogCaptureFixture,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
        server: MyAsyncUDPServer,
    ) -> None:
        caplog.set_level(logging.ERROR, server.logger.name)
        endpoint = await client_factory()

        request_handler.raise_error = True
        await endpoint.sendto(b"something", None)
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.5):
                await endpoint.recvfrom()
        assert len(caplog.records) == 3
        request_handler.raise_error = False
        await endpoint.sendto(b"hello world", None)
        assert (await endpoint.recvfrom())[0] == b"hello world"

    @pytest.mark.parametrize("request_handler", [RequestRefusedHandler], indirect=True)
    @pytest.mark.parametrize("refuse_after", [0, 5], ids=lambda p: f"refuse_after=={p}")
    async def test____serve_forever____request_handler_did_not_yield(
        self,
        refuse_after: int,
        request_handler: RequestRefusedHandler,
        caplog: pytest.LogCaptureFixture,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
        server: MyAsyncUDPServer,
    ) -> None:
        request_handler.bypass_refusal = False
        request_handler.refuse_after = refuse_after
        caplog.set_level(logging.ERROR, server.logger.name)
        endpoint = await client_factory()

        for _ in range(refuse_after):
            await endpoint.sendto(b"a", None)
            assert (await endpoint.recvfrom())[0] == b"a"

        await endpoint.sendto(b"something", None)
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.5):
                await endpoint.recvfrom()
        assert len(caplog.records) == 0
        request_handler.bypass_refusal = True
        await endpoint.sendto(b"hello world", None)
        assert (await endpoint.recvfrom())[0] == b"hello world"

    @pytest.mark.parametrize("request_handler", [ConcurrencyTestRequestHandler], indirect=True)
    async def test____serve_forever____datagram_while_request_handle_is_performed(
        self,
        request_handler: ConcurrencyTestRequestHandler,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
    ) -> None:
        request_handler.sleep_time_before_second_yield = 0.5
        endpoint = await client_factory()

        await endpoint.sendto(b"something", None)
        await endpoint.sendto(b"hello, world.", None)
        async with asyncio.timeout(5):
            assert (await endpoint.recvfrom())[0] == b"After wait: hello, world."

    @pytest.mark.parametrize("request_handler", [ConcurrencyTestRequestHandler], indirect=True)
    async def test____serve_forever____too_many_datagrams_while_request_handle_is_performed(
        self,
        request_handler: ConcurrencyTestRequestHandler,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
    ) -> None:
        request_handler.sleep_time_before_response = 0.5
        endpoint = await client_factory()

        await endpoint.sendto(b"something", None)
        await asyncio.sleep(0.1)
        await endpoint.sendto(b"hello, world.", None)
        await endpoint.sendto(b"something", None)
        await asyncio.sleep(0.1)
        await endpoint.sendto(b"hello, world. new game +", None)
        async with asyncio.timeout(5):
            assert (await endpoint.recvfrom())[0] == b"After wait: hello, world."
            assert (await endpoint.recvfrom())[0] == b"After wait: hello, world. new game +"
