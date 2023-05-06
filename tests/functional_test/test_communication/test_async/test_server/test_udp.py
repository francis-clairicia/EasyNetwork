# -*- coding: Utf-8 -*-

from __future__ import annotations

import asyncio
import collections
import contextlib
import logging
from typing import Any, AsyncIterator, Awaitable, Callable

from easynetwork.api_async.backend.abc import AbstractAsyncBackend
from easynetwork.api_async.server.handler import AsyncClientInterface, AsyncDatagramRequestHandler
from easynetwork.api_async.server.udp import AsyncUDPNetworkServer
from easynetwork.exceptions import BaseProtocolParseError, ClientClosedError, DatagramProtocolParseError
from easynetwork.protocol import DatagramProtocol
from easynetwork.tools.socket import SocketAddress
from easynetwork_asyncio.datagram.endpoint import DatagramEndpoint, create_datagram_endpoint

import pytest
import pytest_asyncio

from .....pytest_plugins.asyncio_event_loop import EventLoop
from .base import BaseTestAsyncServer


class RandomErrorWithLogs(Exception):
    pass


class RandomError(Exception):
    pass


class MyAsyncUDPRequestHandler(AsyncDatagramRequestHandler[str, str]):
    request_received: collections.defaultdict[tuple[Any, ...], list[str]]
    bad_request_received: collections.defaultdict[tuple[Any, ...], list[BaseProtocolParseError]]
    refuse_requests_from_address: set[tuple[Any, ...]]
    backend: AbstractAsyncBackend
    service_actions_count: int

    async def service_init(self, backend: AbstractAsyncBackend) -> None:
        await super().service_init(backend)
        self.backend = backend
        self.service_actions_count = 0
        self.refuse_requests_from_address = set()
        self.request_received = collections.defaultdict(list)
        self.bad_request_received = collections.defaultdict(list)

    async def service_actions(self) -> None:
        await super().service_actions()
        self.service_actions_count += 1

    async def service_quit(self) -> None:
        del (
            self.refuse_requests_from_address,
            self.backend,
            self.service_actions_count,
            self.request_received,
            self.bad_request_received,
        )
        await super().service_quit()

    async def accept_request_from(self, client_address: SocketAddress) -> bool:
        return await super().accept_request_from(client_address) and client_address not in self.refuse_requests_from_address

    async def handle(self, request: str, client: AsyncClientInterface[str]) -> None:
        match request:
            case "__error_with_logs__":
                raise RandomErrorWithLogs("Sorry man!")
            case "__error__":
                raise RandomError("Sorry man!")
            case "__os_error__":
                raise OSError("Server issue.")
            case _:
                self.request_received[client.address].append(request)
                await client.send_packet(request.upper())

    async def handle_error(self, client: AsyncClientInterface[str], exc: Exception) -> bool:
        if isinstance(exc, OSError):
            assert client.is_closing()
            with pytest.raises(ClientClosedError):
                await client.send_packet(f'{exc.__class__.__name__}("{exc}")')
            return False

        assert not client.is_closing()
        await client.send_packet(f'{exc.__class__.__name__}("{exc}")')
        match exc:
            case RandomErrorWithLogs():
                return await super().handle_error(client, exc)
            case _:
                return True

    async def bad_request(self, client: AsyncClientInterface[str], exc: BaseProtocolParseError) -> None:
        await super().bad_request(client, exc)
        self.bad_request_received[client.address].append(exc)
        await client.send_packet("wrong encoding man.")


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
    def request_handler() -> MyAsyncUDPRequestHandler:
        return MyAsyncUDPRequestHandler()

    @pytest_asyncio.fixture
    @staticmethod
    async def server(
        request_handler: MyAsyncUDPRequestHandler,
        socket_family: int,
        localhost_ip: str,
        unused_udp_port_factory: Callable[[], int],
        datagram_protocol: DatagramProtocol[str, str],
        backend_kwargs: dict[str, Any],
    ) -> AsyncIterator[MyAsyncUDPServer]:
        async with MyAsyncUDPServer(
            localhost_ip,
            unused_udp_port_factory(),
            datagram_protocol,
            request_handler,
            family=socket_family,
            backend_kwargs=backend_kwargs,
        ) as server:
            assert server.socket is None
            yield server

    @pytest_asyncio.fixture
    @staticmethod
    async def server_address(run_server: None, server: MyAsyncUDPServer) -> tuple[str, int]:
        async with asyncio.timeout(1):
            await server.wait_for_server_to_be_up()
        assert server.is_serving()
        assert server.socket is not None
        return server.socket.getsockname()[:2]

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
        unused_udp_port: int,
        request_handler: MyAsyncUDPRequestHandler,
        datagram_protocol: DatagramProtocol[str, str],
        backend_kwargs: dict[str, Any],
    ) -> None:
        async with MyAsyncUDPServer(
            host, unused_udp_port, datagram_protocol, request_handler, backend_kwargs=backend_kwargs
        ) as s:
            _ = asyncio.create_task(s.serve_forever())
            async with asyncio.timeout(1):
                await s.wait_for_server_to_be_up()

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
    async def test____serve_forever____service_actions(self, request_handler: MyAsyncUDPRequestHandler) -> None:
        await asyncio.sleep(0.2)
        assert request_handler.service_actions_count >= 1

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

    async def test____serve_forever____request_refused(
        self,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
        request_handler: MyAsyncUDPRequestHandler,
        caplog: pytest.LogCaptureFixture,
        server: MyAsyncUDPServer,
    ) -> None:
        caplog.set_level(logging.WARNING, server.logger.name)
        endpoint = await client_factory()
        client_address: tuple[Any, ...] = endpoint.get_extra_info("sockname")
        host, port = client_address[:2]

        request_handler.refuse_requests_from_address.add(client_address)

        await endpoint.sendto(b"hello, world.", None)
        await asyncio.sleep(0.2)

        assert request_handler.request_received[client_address] == []
        assert caplog.record_tuples == [(server.logger.name, logging.WARNING, f"A datagram from {host}:{port} has been refused")]

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
        assert request_handler.bad_request_received[client_address][0].__traceback__ is None

    @pytest.mark.parametrize("with_logs", [False, True], ids=lambda boolean: f"with_logs=={boolean}")
    async def test____serve_forever____unexpected_error_during_process(
        self,
        with_logs: bool,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
        caplog: pytest.LogCaptureFixture,
        server: MyAsyncUDPServer,
    ) -> None:
        caplog.set_level(logging.ERROR, server.logger.name)
        endpoint = await client_factory()

        if with_logs:
            await endpoint.sendto(b"__error_with_logs__", None)
        else:
            await endpoint.sendto(b"__error__", None)
        await asyncio.sleep(0.2)

        if with_logs:
            assert (await endpoint.recvfrom())[0] == b'RandomErrorWithLogs("Sorry man!")'
            assert len(caplog.records) > 0
        else:
            assert (await endpoint.recvfrom())[0] == b'RandomError("Sorry man!")'
            assert len(caplog.records) == 0

    async def test____serve_forever____os_error(
        self,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
    ) -> None:
        endpoint = await client_factory()

        await endpoint.sendto(b"__os_error__", None)
        await asyncio.sleep(0.2)
