# -*- coding: utf-8 -*-

from __future__ import annotations

import asyncio
import collections
import contextlib
import logging
import math
from typing import Any, AsyncGenerator, AsyncIterator, Awaitable, Callable

from easynetwork.api_async.backend.abc import AbstractAsyncBackend
from easynetwork.api_async.server.handler import AsyncBaseRequestHandler, AsyncClientInterface
from easynetwork.api_async.server.udp import AsyncUDPNetworkServer
from easynetwork.exceptions import BaseProtocolParseError, ClientClosedError, DatagramProtocolParseError
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
        self.bad_request_received[client.address].append(exc)
        await client.send_packet("wrong encoding man.")


class TimeoutRequestHandler(AsyncBaseRequestHandler[str, str]):
    async def handle(self, client: AsyncClientInterface[str]) -> AsyncGenerator[None, str]:
        assert (yield) == "something"
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(1):
                yield
        await client.send_packet("successfully timed out")

    async def bad_request(self, client: AsyncClientInterface[str], exc: BaseProtocolParseError, /) -> None:
        pass


class CancellationRequestHandler(AsyncBaseRequestHandler[str, str]):
    async def handle(self, client: AsyncClientInterface[str]) -> AsyncGenerator[None, str]:
        yield
        await client.send_packet("response")
        raise asyncio.CancelledError()

    async def bad_request(self, client: AsyncClientInterface[str], exc: BaseProtocolParseError, /) -> None:
        pass


class InvalidRequestHandler(AsyncBaseRequestHandler[str, str]):
    async def handle(self, client: AsyncClientInterface[str]) -> AsyncGenerator[None, str]:
        return
        request = yield  # type: ignore[unreachable]
        await client.send_packet(request)

    async def bad_request(self, client: AsyncClientInterface[str], exc: BaseProtocolParseError, /) -> None:
        pass


class ErrorInBadRequestHandler(AsyncBaseRequestHandler[str, str]):
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

    @pytest.mark.parametrize("host", [None, ""], ids=repr)
    async def test____dunder_init____bind_on_all_available_interfaces(
        self,
        host: str | None,
        request_handler: MyAsyncUDPRequestHandler,
        datagram_protocol: DatagramProtocol[str, str],
        backend_kwargs: dict[str, Any],
    ) -> None:
        async with MyAsyncUDPServer(host, 0, datagram_protocol, request_handler, backend_kwargs=backend_kwargs) as s:
            is_up_event = asyncio.Event()
            _ = asyncio.create_task(s.serve_forever(is_up_event=is_up_event))
            async with asyncio.timeout(1):
                await is_up_event.wait()

            assert s.socket is not None
            assert s.get_protocol() is datagram_protocol

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
        assert request_handler.bad_request_received[client_address][0].error_type == "deserialization"

    @pytest.mark.parametrize("mute_thrown_exception", [False, True])
    @pytest.mark.parametrize("request_handler", [ErrorInBadRequestHandler], indirect=True)
    async def test____serve_forever____bad_request____unexpected_error(
        self,
        mute_thrown_exception: bool,
        request_handler: ErrorInBadRequestHandler,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
        caplog: pytest.LogCaptureFixture,
        server: MyAsyncUDPServer,
    ) -> None:
        caplog.set_level(logging.ERROR, server.logger.name)
        request_handler.mute_thrown_exception = mute_thrown_exception
        endpoint = await client_factory()

        await endpoint.sendto("\u00E9".encode("latin-1"), None)  # StringSerializer does not accept unicode
        await asyncio.sleep(0.1)

        assert (await endpoint.recvfrom())[0] == b"RandomError: An error occurred"
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
    ) -> None:
        endpoint = await client_factory()

        await endpoint.sendto(b"__os_error__", None)
        await asyncio.sleep(0.2)

    async def test____serve_forever____close_is_noop(
        self,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
    ) -> None:
        endpoint = await client_factory()

        await endpoint.sendto(b"__close__", None)
        await asyncio.sleep(0.1)

        assert (await endpoint.recvfrom())[0] == b"not closed X)"

    @pytest.mark.parametrize("request_handler", [TimeoutRequestHandler], indirect=True)
    async def test____serve_forever____throw_cancelled_error(
        self,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
    ) -> None:
        endpoint = await client_factory()

        await endpoint.sendto(b"something", None)
        assert (await endpoint.recvfrom())[0] == b"successfully timed out"

    @pytest.mark.parametrize("request_handler", [CancellationRequestHandler], indirect=True)
    async def test____serve_forever____request_handler_is_cancelled(
        self,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
    ) -> None:
        endpoint = await client_factory()

        await endpoint.sendto(b"something", None)
        assert (await endpoint.recvfrom())[0] == b"response"

    @pytest.mark.parametrize("request_handler", [InvalidRequestHandler], indirect=True)
    async def test____serve_forever____request_handler_did_not_yield(
        self,
        caplog: pytest.LogCaptureFixture,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
        server: MyAsyncUDPServer,
    ) -> None:
        caplog.set_level(logging.ERROR, server.logger.name)
        endpoint = await client_factory()

        await endpoint.sendto(b"something", None)
        await asyncio.sleep(0.5)
        assert len(caplog.records) == 3
