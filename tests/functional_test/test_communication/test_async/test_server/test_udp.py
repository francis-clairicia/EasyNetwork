from __future__ import annotations

import asyncio
import collections
import contextlib
import logging
import math
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from typing import Any

from easynetwork.api_async.backend.abc import AbstractAsyncBackend
from easynetwork.api_async.server.handler import AsyncBaseRequestHandler, AsyncClientInterface
from easynetwork.api_async.server.udp import AsyncUDPNetworkServer
from easynetwork.exceptions import BaseProtocolParseError, ClientClosedError, DatagramProtocolParseError, DeserializeError
from easynetwork.protocol import DatagramProtocol
from easynetwork_asyncio.datagram.endpoint import DatagramEndpoint, create_datagram_endpoint

import pytest
import pytest_asyncio

from .....pytest_plugins.asyncio_event_loop import EventLoop
from .base import BaseTestAsyncServer


class RandomError(Exception):
    pass


class MyAsyncUDPRequestHandler(AsyncBaseRequestHandler[str, str]):
    request_received: collections.defaultdict[tuple[Any, ...], list[str]]
    bad_request_received: collections.defaultdict[tuple[Any, ...], list[BaseProtocolParseError]]
    created_clients: set[AsyncClientInterface[str]]
    backend: AbstractAsyncBackend
    service_actions_count: int
    crash_service_actions: bool = False

    def set_async_backend(self, backend: AbstractAsyncBackend) -> None:
        self.backend = backend

    async def service_init(self) -> None:
        await super().service_init()
        self.service_actions_count = 0
        self.request_received = collections.defaultdict(list)
        self.bad_request_received = collections.defaultdict(list)
        self.created_clients = set()

    async def service_actions(self) -> None:
        if self.crash_service_actions:
            raise Exception("CRASH")
        await super().service_actions()
        self.service_actions_count += 1

    async def service_quit(self) -> None:
        # At this point, ALL clients should be closed (since the UDP socket is closed)
        for client in self.created_clients:
            assert client.is_closing()
            with pytest.raises(ClientClosedError):
                await client.send_packet("something")

        del (
            self.service_actions_count,
            self.request_received,
            self.bad_request_received,
            self.created_clients,
        )
        await super().service_quit()

    async def handle(self, client: AsyncClientInterface[str]) -> AsyncGenerator[None, str]:
        self.created_clients.add(client)
        match (yield):
            case "__error__":
                raise RandomError("Sorry man!")
            case "__os_error__":
                raise OSError("Server issue.")
            case "__close__":
                await client.aclose()
                assert not client.is_closing()
                await client.send_packet("not closed X)")
            case "__closed_client_error__":
                raise ClientClosedError
            case "__eq__":
                assert client in list(self.created_clients)
                assert object() not in list(self.created_clients)
                await client.send_packet("True")
            case "__wait__":
                request = yield
                self.request_received[client.address].append(request)
                await client.send_packet(f"After wait: {request}")
            case request:
                self.request_received[client.address].append(request)
                await client.send_packet(request.upper())

    async def bad_request(self, client: AsyncClientInterface[str], exc: BaseProtocolParseError) -> None:
        assert isinstance(exc, DatagramProtocolParseError)
        assert exc.sender_address == client.address
        self.bad_request_received[client.address].append(exc)
        await client.send_packet("wrong encoding man.")


class TimeoutRequestHandler(AsyncBaseRequestHandler[str, str]):
    request_timeout: float = 1.0

    async def handle(self, client: AsyncClientInterface[str]) -> AsyncGenerator[None, str]:
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

    async def bad_request(self, client: AsyncClientInterface[str], exc: BaseProtocolParseError, /) -> None:
        pass


class ConcurrencyTestRequestHandler(AsyncBaseRequestHandler[str, str]):
    sleep_time_before_second_yield: float = 0.0
    sleep_time_before_response: float = 0.0

    async def handle(self, client: AsyncClientInterface[str]) -> AsyncGenerator[None, str]:
        assert (yield) == "something"
        await asyncio.sleep(self.sleep_time_before_second_yield)
        request = yield
        await asyncio.sleep(self.sleep_time_before_response)
        await client.send_packet(f"After wait: {request}")

    async def bad_request(self, client: AsyncClientInterface[str], exc: BaseProtocolParseError, /) -> None:
        pass


class CancellationRequestHandler(AsyncBaseRequestHandler[str, str]):
    async def handle(self, client: AsyncClientInterface[str]) -> AsyncGenerator[None, str]:
        yield
        await client.send_packet("response")
        raise asyncio.CancelledError()

    async def bad_request(self, client: AsyncClientInterface[str], exc: BaseProtocolParseError, /) -> None:
        pass


class RequestRefusedHandler(AsyncBaseRequestHandler[str, str]):
    refuse_after: int = 2**64
    bypass_refusal: bool = False

    async def service_init(self) -> None:
        self.request_count: collections.Counter[AsyncClientInterface[str]] = collections.Counter()

    async def handle(self, client: AsyncClientInterface[str]) -> AsyncGenerator[None, str]:
        if self.request_count[client] >= self.refuse_after and not self.bypass_refusal:
            return
        request = yield
        self.request_count[client] += 1
        await client.send_packet(request)

    async def bad_request(self, client: AsyncClientInterface[str], exc: BaseProtocolParseError, /) -> None:
        pass


class ErrorInRequestHandler(AsyncBaseRequestHandler[str, str]):
    mute_thrown_exception: bool = False

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


class ErrorBeforeYieldHandler(AsyncBaseRequestHandler[str, str]):
    raise_error: bool = False

    async def handle(self, client: AsyncClientInterface[str]) -> AsyncGenerator[None, str]:
        if self.raise_error:
            raise RandomError("An error occurred")
        request = yield
        await client.send_packet(request)

    async def bad_request(self, client: AsyncClientInterface[str], exc: BaseProtocolParseError, /) -> None:
        pass


class CloseHandleAfterBadRequest(AsyncBaseRequestHandler[str, str]):
    bad_request_return_value: bool | None = None

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
    def request_handler(request: Any) -> AsyncBaseRequestHandler[str, str]:
        request_handler_cls: type[AsyncBaseRequestHandler[str, str]] = getattr(request, "param", MyAsyncUDPRequestHandler)
        return request_handler_cls()

    @pytest.fixture
    @staticmethod
    def service_actions_interval(request: Any) -> float | None:
        return getattr(request, "param", None)

    @pytest_asyncio.fixture
    @staticmethod
    async def server(
        request_handler: AsyncBaseRequestHandler[str, str],
        localhost_ip: str,
        datagram_protocol: DatagramProtocol[str, str],
        service_actions_interval: float | None,
        backend_kwargs: dict[str, Any],
    ) -> AsyncIterator[MyAsyncUDPServer]:
        async with MyAsyncUDPServer(
            localhost_ip,
            0,
            datagram_protocol,
            request_handler,
            service_actions_interval=service_actions_interval,
            backend_kwargs=backend_kwargs,
        ) as server:
            assert server.socket is None
            assert server.get_address() is None
            yield server

    @pytest_asyncio.fixture
    @staticmethod
    async def server_address(run_server: asyncio.Event, server: MyAsyncUDPServer) -> tuple[str, int]:
        async with asyncio.timeout(1):
            await run_server.wait()
        assert server.is_serving()
        assert server.socket is not None
        server_address = server.get_address()
        assert server_address is not None
        return server_address.for_connection()

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
                stack.push_async_callback(endpoint.wait_closed)
                stack.callback(endpoint.close)
                return endpoint

            yield factory

    @pytest.fixture(
        params=[
            pytest.param(True, id="TaskGroup.start_soon_with_context available"),
            pytest.param(False, id="TaskGroup.start_soon_with_context unavailable"),
        ]
    )
    @staticmethod
    def start_task_with_context(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
        match getattr(request, "param"):
            case True:
                pass
            case False:
                from easynetwork.api_async.backend.abc import AbstractTaskGroup
                from easynetwork_asyncio.tasks import TaskGroup

                monkeypatch.setattr(TaskGroup, "start_soon_with_context", AbstractTaskGroup.start_soon_with_context)
            case invalid_param:
                pytest.fail(f"Invalid param: {invalid_param!r}")

    async def test____dunder_init____bind_on_localhost_by_default(
        self,
        request_handler: MyAsyncUDPRequestHandler,
        datagram_protocol: DatagramProtocol[str, str],
        backend_kwargs: dict[str, Any],
    ) -> None:
        async with MyAsyncUDPServer(None, 0, datagram_protocol, request_handler, backend_kwargs=backend_kwargs) as s:
            is_up_event = asyncio.Event()
            _ = asyncio.create_task(s.serve_forever(is_up_event=is_up_event))
            async with asyncio.timeout(1):
                await is_up_event.wait()

            try:
                assert s.socket is not None
                assert (address := s.get_address()) is not None and address.host in ("127.0.0.1", "::1")
            finally:
                await s.shutdown()

    @pytest.mark.usefixtures("run_server_and_wait")
    async def test____serve_forever____backend_assignment(
        self,
        server: MyAsyncUDPServer,
        request_handler: MyAsyncUDPRequestHandler,
    ) -> None:
        assert request_handler.backend is server.get_backend()

    @pytest.mark.usefixtures("run_server_and_wait")
    @pytest.mark.parametrize("service_actions_interval", [0.1], indirect=True)
    async def test____serve_forever____service_actions(self, request_handler: MyAsyncUDPRequestHandler) -> None:
        await asyncio.sleep(0.2)
        assert request_handler.service_actions_count >= 1

    @pytest.mark.usefixtures("run_server_and_wait")
    @pytest.mark.parametrize("service_actions_interval", [math.inf], indirect=True)
    async def test____serve_forever____service_actions____disabled(self, request_handler: MyAsyncUDPRequestHandler) -> None:
        await asyncio.sleep(1)
        assert request_handler.service_actions_count == 0

    @pytest.mark.usefixtures("run_server_and_wait")
    @pytest.mark.parametrize("service_actions_interval", [0.1], indirect=True)
    async def test____serve_forever____service_actions____crash(
        self,
        request_handler: MyAsyncUDPRequestHandler,
        caplog: pytest.LogCaptureFixture,
        server: MyAsyncUDPServer,
    ) -> None:
        caplog.set_level(logging.ERROR, server.logger.name)
        request_handler.crash_service_actions = True
        await asyncio.sleep(0.5)
        assert request_handler.service_actions_count == 0
        assert "Error occurred in request_handler.service_actions()" in [rec.message for rec in caplog.records]

    async def test____serve_forever____handle_request(
        self,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
        request_handler: MyAsyncUDPRequestHandler,
    ) -> None:
        endpoint = await client_factory()
        client_address: tuple[Any, ...] = endpoint.get_extra_info("sockname")

        await endpoint.sendto(b"hello, world.", None)
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

    @pytest.mark.parametrize("request_handler", [CloseHandleAfterBadRequest], indirect=True)
    @pytest.mark.parametrize("bad_request_return_value", [None, False, True])
    async def test____serve_forever____bad_request____return_value(
        self,
        bad_request_return_value: bool | None,
        request_handler: CloseHandleAfterBadRequest,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
    ) -> None:
        request_handler.bad_request_return_value = bad_request_return_value
        endpoint = await client_factory()

        await endpoint.sendto("\u00E9".encode("latin-1"), None)  # StringSerializer does not accept unicode
        await asyncio.sleep(0.1)
        assert (await endpoint.recvfrom())[0] == b"new handle"

        assert (await endpoint.recvfrom())[0] == b"wrong encoding"
        await endpoint.sendto(b"something valid", None)
        await asyncio.sleep(0.1)

        if bad_request_return_value in (None, False):
            assert (await endpoint.recvfrom())[0] == b"GeneratorExit"
            assert (await endpoint.recvfrom())[0] == b"new handle"

        assert (await endpoint.recvfrom())[0] == b"something valid"

    @pytest.mark.parametrize("request_handler", [ErrorInRequestHandler], indirect=True)
    async def test____serve_forever____bad_request____unexpected_error(
        self,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
        caplog: pytest.LogCaptureFixture,
        server: MyAsyncUDPServer,
    ) -> None:
        caplog.set_level(logging.ERROR, server.logger.name)
        endpoint = await client_factory()

        await endpoint.sendto("\u00E9".encode("latin-1"), None)  # StringSerializer does not accept unicode
        await asyncio.sleep(0.2)

        with pytest.raises(TimeoutError):
            async with asyncio.timeout(1):
                await endpoint.recvfrom()
                pytest.fail("Should not arrive here")
        assert len(caplog.records) == 3

    async def test____serve_forever____bad_request____recursive_traceback_frame_clear_error(
        self,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
        caplog: pytest.LogCaptureFixture,
        server: MyAsyncUDPServer,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        caplog.set_level(logging.WARNING, server.logger.name)
        endpoint = await client_factory()

        def infinite_recursion(exc: BaseException) -> None:
            infinite_recursion(exc)

        monkeypatch.setattr(
            f"{AsyncUDPNetworkServer.__module__}._recursively_clear_exception_traceback_frames",
            infinite_recursion,
        )

        await endpoint.sendto("\u00E9".encode("latin-1"), None)  # StringSerializer does not accept unicode
        await asyncio.sleep(0.1)

        assert (await endpoint.recvfrom())[0] == b"wrong encoding man."
        assert "Recursion depth reached when clearing exception's traceback frames" in [rec.message for rec in caplog.records]

    @pytest.mark.parametrize("mute_thrown_exception", [False, True])
    @pytest.mark.parametrize("request_handler", [ErrorInRequestHandler], indirect=True)
    @pytest.mark.parametrize("serializer", [pytest.param("invalid", id="serializer_crash")], indirect=True)
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

        await endpoint.sendto(b"something", None)
        await asyncio.sleep(0.2)

        assert (await endpoint.recvfrom())[0] == b"SystemError: CRASH"
        if mute_thrown_exception:
            await endpoint.sendto(b"something", None)
            await asyncio.sleep(0.2)
            assert (await endpoint.recvfrom())[0] == b"SystemError: CRASH"
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

    async def test____serve_forever____close_is_noop(
        self,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
    ) -> None:
        endpoint = await client_factory()

        await endpoint.sendto(b"__close__", None)
        await asyncio.sleep(0.1)

        assert (await endpoint.recvfrom())[0] == b"not closed X)"

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

    @pytest.mark.usefixtures("start_task_with_context")
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

    @pytest.mark.usefixtures("start_task_with_context")
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
