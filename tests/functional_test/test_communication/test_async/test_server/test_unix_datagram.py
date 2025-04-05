# mypy: disable_error_code=override
from __future__ import annotations

import asyncio
import collections
import contextlib
import errno
import logging
import os
import stat
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING, Any, Literal

from easynetwork.exceptions import (
    BaseProtocolParseError,
    ClientClosedError,
    DatagramProtocolParseError,
    DeserializeError,
    TypedAttributeLookupError,
)
from easynetwork.lowlevel._utils import remove_traceback_frames_in_place
from easynetwork.lowlevel.api_async.backend._asyncio.backend import AsyncIOBackend
from easynetwork.lowlevel.api_async.backend._asyncio.datagram.endpoint import DatagramEndpoint, create_datagram_endpoint
from easynetwork.lowlevel.socket import SocketProxy, UnixSocketAddress
from easynetwork.protocol import DatagramProtocol
from easynetwork.servers.async_unix_datagram import AsyncUnixDatagramServer, _UnnamedAddressesBehavior
from easynetwork.servers.handlers import AsyncDatagramClient, AsyncDatagramRequestHandler, UNIXClientAttribute

import pytest
import pytest_asyncio

from .....pytest_plugins.unix_sockets import UnixSocketPathFactory
from .....tools import PlatformMarkers, is_uvloop_event_loop
from .base import BaseTestAsyncServer

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


class RandomError(Exception):
    pass


def fetch_client_address(client: AsyncDatagramClient[Any]) -> str | bytes:
    return client.extra(UNIXClientAttribute.peer_name).as_raw()


LOGGER = logging.getLogger(__name__)


class MyDatagramRequestHandler(AsyncDatagramRequestHandler[str, str]):
    request_count: collections.Counter[str | bytes]
    request_received: collections.defaultdict[str | bytes, list[str]]
    bad_request_received: collections.defaultdict[str | bytes, list[BaseProtocolParseError]]
    created_clients: set[AsyncDatagramClient[str]]
    created_clients_map: dict[str | bytes, AsyncDatagramClient[str]]
    server: AsyncUnixDatagramServer[str, str]

    async def service_init(self, exit_stack: contextlib.AsyncExitStack, server: AsyncUnixDatagramServer[str, str]) -> None:
        await super().service_init(exit_stack, server)
        self.server = server
        assert isinstance(self.server, AsyncUnixDatagramServer)

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

        exit_stack.push_async_callback(self.service_quit)

    async def service_quit(self) -> None:
        # At this point, ALL clients should be closed (since the socket is closed)
        for client in self.created_clients:
            assert client.is_closing()
            with pytest.raises(ClientClosedError):
                await client.send_packet("something")

    async def handle(self, client: AsyncDatagramClient[str]) -> AsyncGenerator[None, str]:
        self.created_clients.add(client)
        self.created_clients_map.setdefault(fetch_client_address(client), client)
        while True:
            async with self.handle_bad_requests(client):
                request = yield
                break
        self.request_count[fetch_client_address(client)] += 1
        match request:
            case "__ping__":
                await client.send_packet("pong")
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
                    await client.send_packet(f"False: {exc}")
                    LOGGER.error("AssertionError", exc_info=exc)
                else:
                    await client.send_packet("True")
            case "__cache__":
                stored_client_object = self.created_clients_map[fetch_client_address(client)]
                try:
                    assert client is stored_client_object, "client is not stored_client_object"
                except AssertionError as exc:
                    await client.send_packet(f"False: {exc}")
                    LOGGER.error("AssertionError", exc_info=exc)
                else:
                    await client.send_packet("True")
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

    @contextlib.asynccontextmanager
    async def handle_bad_requests(self, client: AsyncDatagramClient[str]) -> AsyncIterator[None]:
        try:
            yield
        except DatagramProtocolParseError as exc:
            remove_traceback_frames_in_place(exc, 1)
            self.bad_request_received[fetch_client_address(client)].append(exc)
            await client.send_packet("wrong encoding man.")


class TimeoutYieldedRequestHandler(AsyncDatagramRequestHandler[str, str]):
    request_timeout: float = 1.0
    timeout_on_third_yield: bool = False

    async def handle(self, client: AsyncDatagramClient[str]) -> AsyncGenerator[float | None, str]:
        assert (yield None) == "something"
        if self.timeout_on_third_yield:
            request = yield None
            await client.send_packet(request)
        try:
            with pytest.raises(TimeoutError):
                yield self.request_timeout
            await client.send_packet("successfully timed out")
        except BaseException:
            await client.send_packet("error occurred")
            raise
        finally:
            self.request_timeout = 1.0  # Force reset to 1 second in order not to overload the server


class TimeoutContextRequestHandler(AsyncDatagramRequestHandler[str, str]):
    request_timeout: float = 1.0
    timeout_on_third_yield: bool = False

    async def handle(self, client: AsyncDatagramClient[str]) -> AsyncGenerator[None, str]:
        assert (yield) == "something"
        if self.timeout_on_third_yield:
            request = yield
            await client.send_packet(request)
        try:
            with pytest.raises(TimeoutError):
                with client.backend().timeout(self.request_timeout):
                    yield
            await client.send_packet("successfully timed out")
        except BaseException:
            await client.send_packet("error occurred")
            raise
        finally:
            self.request_timeout = 1.0  # Force reset to 1 second in order not to overload the server


class ConcurrencyTestRequestHandler(AsyncDatagramRequestHandler[str, str]):
    sleep_time_before_second_yield: float | None = None
    sleep_time_before_response: float | None = None
    recreate_generator: bool = True
    ignore_cancellation: bool = False

    async def handle(self, client: AsyncDatagramClient[str]) -> AsyncGenerator[None, str]:
        while True:
            assert (yield) == "something"
            if self.sleep_time_before_second_yield is not None:
                if self.ignore_cancellation:
                    await client.backend().ignore_cancellation(asyncio.sleep(self.sleep_time_before_second_yield))
                else:
                    await asyncio.sleep(self.sleep_time_before_second_yield)
            request = yield
            if self.sleep_time_before_response is not None:
                if self.ignore_cancellation:
                    await client.backend().ignore_cancellation(asyncio.sleep(self.sleep_time_before_response))
                else:
                    await asyncio.sleep(self.sleep_time_before_response)
            if self.ignore_cancellation:
                await client.backend().ignore_cancellation(client.send_packet(f"After wait: {request}"))
            else:
                await client.send_packet(f"After wait: {request}")
            if self.recreate_generator:
                break


class CancellationRequestHandler(AsyncDatagramRequestHandler[str, str]):
    async def handle(self, client: AsyncDatagramClient[str]) -> AsyncGenerator[None, str]:
        yield
        await client.send_packet("response")
        raise asyncio.CancelledError()


class RequestRefusedHandler(AsyncDatagramRequestHandler[str, str]):
    refuse_after: int = 2**64
    bypass_refusal: bool = False

    async def service_init(self, exit_stack: contextlib.AsyncExitStack, server: Any) -> None:
        self.request_count: collections.Counter[AsyncDatagramClient[str]] = collections.Counter()
        exit_stack.callback(self.request_count.clear)

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


class MyAsyncUnixDatagramServer(AsyncUnixDatagramServer[str, str]):
    __slots__ = ()


_UnixAddressTypeLiteral = Literal["PATHNAME", "ABSTRACT"]


@pytest.mark.flaky(retries=3, delay=0.1)
@PlatformMarkers.skipif_platform_win32
class TestAsyncUnixDatagramServer(BaseTestAsyncServer):
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
                if is_uvloop_event_loop(event_loop):
                    # Addresses received through uvloop transports contains extra NULL bytes because the creation of
                    # the bytes object from the sockaddr_un structure does not take into account the real addrlen.
                    # https://github.com/MagicStack/uvloop/blob/v0.21.0/uvloop/includes/compat.h#L34-L55
                    pytest.xfail("uvloop translation of abstract unix sockets to python object is wrong.")
                return param
            case _:
                pytest.fail(f"Invalid use_unix_address_type parameter: {request.param}")

    @pytest.fixture
    @staticmethod
    def request_handler(request: pytest.FixtureRequest) -> AsyncDatagramRequestHandler[str, str]:
        request_handler_cls: type[AsyncDatagramRequestHandler[str, str]] = getattr(request, "param", MyDatagramRequestHandler)
        return request_handler_cls()

    @pytest.fixture
    @staticmethod
    def unnamed_addresses_behavior(request: pytest.FixtureRequest) -> _UnnamedAddressesBehavior | None:
        return getattr(request, "param", None)

    @pytest.fixture
    @staticmethod
    def asyncio_backend() -> AsyncIOBackend:
        return AsyncIOBackend()

    @pytest_asyncio.fixture
    @staticmethod
    async def server_not_activated(
        asyncio_backend: AsyncIOBackend,
        request_handler: AsyncDatagramRequestHandler[str, str],
        unix_socket_path_factory: UnixSocketPathFactory,
        datagram_protocol: DatagramProtocol[str, str],
        caplog: pytest.LogCaptureFixture,
        logger_crash_threshold_level: dict[str, int],
    ) -> AsyncIterator[MyAsyncUnixDatagramServer]:
        server = MyAsyncUnixDatagramServer(
            unix_socket_path_factory(),
            datagram_protocol,
            request_handler,
            asyncio_backend,
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
        request_handler: AsyncDatagramRequestHandler[str, str],
        unix_socket_path_factory: UnixSocketPathFactory,
        datagram_protocol: DatagramProtocol[str, str],
        unnamed_addresses_behavior: _UnnamedAddressesBehavior | None,
        caplog: pytest.LogCaptureFixture,
        logger_crash_threshold_level: dict[str, int],
    ) -> AsyncIterator[MyAsyncUnixDatagramServer]:
        if use_unix_address_type == "ABSTRACT":
            # Let the kernel assign us an abstract socket address.
            path = ""
        else:
            path = unix_socket_path_factory()
        async with MyAsyncUnixDatagramServer(
            path,
            datagram_protocol,
            request_handler,
            asyncio_backend,
            unnamed_addresses_behavior=unnamed_addresses_behavior,
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
    async def server_address(run_server: asyncio.Event, server: MyAsyncUnixDatagramServer) -> UnixSocketAddress:
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
    async def client_factory(
        request: pytest.FixtureRequest,
        use_unix_address_type: _UnixAddressTypeLiteral,
        unix_socket_path_factory: UnixSocketPathFactory,
        server_address: UnixSocketAddress,
    ) -> AsyncIterator[Callable[[], Awaitable[DatagramEndpoint]]]:
        from socket import SOCK_DGRAM, socket as SocketType

        from .....fixtures.socket import AF_UNIX_or_skip

        async with contextlib.AsyncExitStack() as stack:

            async def factory() -> DatagramEndpoint:
                event_loop = asyncio.get_running_loop()
                # Caveat: uvloop does not support having a UNIX socket address for "local_addr" and "remote_addr" parameter.
                # The socket must be created manually.
                sock = SocketType(AF_UNIX_or_skip(), SOCK_DGRAM)
                match getattr(request, "param", "CLIENT_BOUND"):
                    case "CLIENT_BOUND":
                        if use_unix_address_type == "ABSTRACT":
                            # Let the kernel assign us an abstract socket address.
                            sock.bind("")
                        else:
                            path = unix_socket_path_factory()
                            sock.bind(path)
                    case "CLIENT_UNBOUND":
                        pass
                    case param:
                        sock.close()
                        pytest.fail(f"Invalid parameter for client_factory: {param!r}")

                sock.setblocking(False)
                await event_loop.sock_connect(sock, server_address.as_raw())

                endpoint = await create_datagram_endpoint(sock=sock)
                stack.push_async_callback(endpoint.aclose)
                return endpoint

            yield factory

    @staticmethod
    async def __ping_server(endpoint: DatagramEndpoint) -> None:
        await endpoint.sendto(b"__ping__", None)
        async with asyncio.timeout(1):
            pong, _ = await endpoint.recvfrom()
            assert pong == b"pong"

    async def test____server_close____while_server_is_running(
        self,
        server: MyAsyncUnixDatagramServer,
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
        server: MyAsyncUnixDatagramServer,
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
        server: MyAsyncUnixDatagramServer,
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
        server: MyAsyncUnixDatagramServer,
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
        server: MyAsyncUnixDatagramServer,
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
        server: MyAsyncUnixDatagramServer,
        request_handler: MyDatagramRequestHandler,
    ) -> None:
        assert request_handler.server == server
        assert isinstance(request_handler.server, AsyncUnixDatagramServer)

    async def test____serve_forever____handle_request(
        self,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
        request_handler: MyDatagramRequestHandler,
    ) -> None:
        endpoint = await client_factory()
        client_address: str | bytes = endpoint.get_extra_info("sockname")

        await endpoint.sendto(b"hello, world.", None)
        async with asyncio.timeout(3):
            assert (await endpoint.recvfrom())[0] == b"HELLO, WORLD."

        assert request_handler.request_received[client_address] == ["hello, world."]

    async def test____serve_forever____handle_request____server_shutdown(
        self,
        server: MyAsyncUnixDatagramServer,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
        request_handler: MyDatagramRequestHandler,
    ) -> None:
        endpoint = await client_factory()
        client_address: str | bytes = endpoint.get_extra_info("sockname")

        await endpoint.sendto(b"hello, world.", None)
        assert client_address not in request_handler.created_clients_map

        async with asyncio.timeout(1):
            await server.shutdown()

    @pytest.mark.parametrize("client_factory", ["CLIENT_UNBOUND"], indirect=True)
    @pytest.mark.parametrize(
        "unnamed_addresses_behavior",
        [None, "ignore", "handle", "warn"],
        indirect=True,
        ids=lambda p: f"unnamed_addresses_behavior=={p!r}",
    )
    async def test____serve_forever____handle_request____from_unbound_socket(
        self,
        unnamed_addresses_behavior: _UnnamedAddressesBehavior | None,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
        request_handler: MyDatagramRequestHandler,
        caplog: pytest.LogCaptureFixture,
        logger_crash_maximum_nb_lines: dict[str, int],
    ) -> None:
        caplog.set_level(logging.WARNING, LOGGER.name)

        endpoint = await client_factory()
        assert endpoint.get_extra_info("sockname") == ""

        await endpoint.sendto(b"hello, world.", None)
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.2):
                _ = await endpoint.recvfrom()

        match unnamed_addresses_behavior:
            case "ignore" | None:  # If None, the default should be "ignore"
                assert request_handler.request_count[""] == 0
                assert "" not in request_handler.request_received
                assert len(caplog.records) == 0
            case "warn":
                logger_crash_maximum_nb_lines[LOGGER.name] = 1
                assert request_handler.request_count[""] == 0
                assert "" not in request_handler.request_received
                assert len(caplog.records) == 1
                assert caplog.records[0].levelno == logging.WARNING
                assert caplog.records[0].getMessage() == "A datagram received from an unbound UNIX datagram socket was dropped."
                assert caplog.records[0].exc_info is None
            case "handle":
                logger_crash_maximum_nb_lines[LOGGER.name] = 1
                assert request_handler.request_count[""] == 1
                assert request_handler.request_received[""] == ["hello, world."]
                assert len(caplog.records) == 1
                assert caplog.records[0].levelno == logging.ERROR
                assert (
                    caplog.records[0].getMessage()
                    == f"OSError: [Errno {errno.EINVAL}] Cannot send a datagram to an unnamed address."
                )
                assert caplog.records[0].exc_info is not None

    async def test____serve_forever____client_extra_attributes(
        self,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
        request_handler: MyDatagramRequestHandler,
    ) -> None:
        all_endpoints: list[DatagramEndpoint] = [await client_factory() for _ in range(3)]

        for endpoint in all_endpoints:
            await self.__ping_server(endpoint)

        assert len(request_handler.created_clients_map) == 3

        for endpoint in all_endpoints:
            client_address: str | bytes = endpoint.get_extra_info("sockname")
            connected_client: AsyncDatagramClient[str] = request_handler.created_clients_map[client_address]

            assert isinstance(connected_client.extra(UNIXClientAttribute.socket), SocketProxy)
            assert connected_client.extra(UNIXClientAttribute.peer_name).as_raw() == client_address
            assert connected_client.extra(UNIXClientAttribute.local_name).as_raw() == endpoint.get_extra_info("peername")
            assert UNIXClientAttribute.peer_credentials not in connected_client.extra_attributes
            with pytest.raises(TypedAttributeLookupError):
                _ = connected_client.extra(UNIXClientAttribute.peer_credentials)

    async def test____serve_forever____client_equality(
        self,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
    ) -> None:
        for _ in range(3):
            endpoint = await client_factory()

            await endpoint.sendto(b"__eq__", None)
            assert (await endpoint.recvfrom())[0] == b"True"

    async def test____serve_forever____client_cache(
        self,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
    ) -> None:
        for _ in range(3):
            endpoint = await client_factory()

            await self.__ping_server(endpoint)

            await endpoint.sendto(b"__cache__", None)
            assert (await endpoint.recvfrom())[0] == b"True"

    async def test____serve_forever____save_request_handler_context(
        self,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
        request_handler: MyDatagramRequestHandler,
    ) -> None:
        endpoint = await client_factory()
        client_address: str | bytes = endpoint.get_extra_info("sockname")

        await endpoint.sendto(b"__wait__", None)
        await endpoint.sendto(b"hello, world.", None)
        assert (await endpoint.recvfrom())[0] == b"After wait: hello, world."

        assert request_handler.request_received[client_address] == ["hello, world."]

    async def test____serve_forever____save_request_handler_context____extra_datagram_are_rescheduled(
        self,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
        request_handler: MyDatagramRequestHandler,
    ) -> None:
        endpoint = await client_factory()
        client_address: str | bytes = endpoint.get_extra_info("sockname")

        await endpoint.sendto(b"__wait__", None)
        await endpoint.sendto(b"hello, world.", None)
        await endpoint.sendto(b"Test 2.", None)
        assert (await endpoint.recvfrom())[0] == b"After wait: hello, world."

        assert set(request_handler.request_received[client_address]) == {"hello, world.", "Test 2."}

    async def test____serve_forever____save_request_handler_context____server_shutdown(
        self,
        server: MyAsyncUnixDatagramServer,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
        request_handler: MyDatagramRequestHandler,
    ) -> None:
        endpoint = await client_factory()
        client_address: str | bytes = endpoint.get_extra_info("sockname")

        await endpoint.sendto(b"__wait__", None)
        async with asyncio.timeout(1):
            while client_address not in request_handler.created_clients_map:
                await asyncio.sleep(0)

        async with asyncio.timeout(1):
            await server.shutdown()

    async def test____serve_forever____bad_request(
        self,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
        request_handler: MyDatagramRequestHandler,
    ) -> None:
        endpoint = await client_factory()
        client_address: str | bytes = endpoint.get_extra_info("sockname")

        await endpoint.sendto("\u00e9".encode("latin-1"), None)  # StringSerializer does not accept unicode
        await asyncio.sleep(0.1)

        assert (await endpoint.recvfrom())[0] == b"wrong encoding man."
        assert request_handler.request_received[client_address] == []
        assert isinstance(request_handler.bad_request_received[client_address][0], DatagramProtocolParseError)
        assert isinstance(request_handler.bad_request_received[client_address][0].error, DeserializeError)

    @pytest.mark.parametrize("mute_thrown_exception", [False, True])
    @pytest.mark.parametrize("request_handler", [ErrorInRequestHandler], indirect=True)
    @pytest.mark.parametrize("datagram_protocol", [pytest.param("invalid", id="serializer_crash")], indirect=True)
    async def test____serve_forever____internal_error(
        self,
        mute_thrown_exception: bool,
        request_handler: ErrorInRequestHandler,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
        caplog: pytest.LogCaptureFixture,
        logger_crash_maximum_nb_lines: dict[str, int],
    ) -> None:
        caplog.set_level(logging.ERROR, LOGGER.name)
        if not mute_thrown_exception:
            logger_crash_maximum_nb_lines[LOGGER.name] = 3
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
            assert caplog.records[1].exc_info is not None
            assert type(caplog.records[1].exc_info[1]) is RuntimeError

    @pytest.mark.parametrize("excgrp", [False, True], ids=lambda p: f"exception_group_raised=={p}")
    async def test____serve_forever____unexpected_error_during_process(
        self,
        excgrp: bool,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
        caplog: pytest.LogCaptureFixture,
        logger_crash_maximum_nb_lines: dict[str, int],
    ) -> None:
        caplog.set_level(logging.ERROR, LOGGER.name)
        logger_crash_maximum_nb_lines[LOGGER.name] = 3
        endpoint = await client_factory()

        if excgrp:
            await endpoint.sendto(b"__error_excgrp__", None)
        else:
            await endpoint.sendto(b"__error__", None)
        await asyncio.sleep(0.2)

        assert len(caplog.records) == 3
        assert caplog.records[1].exc_info is not None
        if excgrp:
            assert type(caplog.records[1].exc_info[1]) is ExceptionGroup
            assert type(caplog.records[1].exc_info[1].exceptions[0]) is RandomError
        else:
            assert type(caplog.records[1].exc_info[1]) is RandomError

    @pytest.mark.parametrize("datagram_protocol", [pytest.param("bad_serialize", id="serializer_crash")], indirect=True)
    async def test____serve_forever____unexpected_error_during_response_serialization(
        self,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
        caplog: pytest.LogCaptureFixture,
        logger_crash_maximum_nb_lines: dict[str, int],
    ) -> None:
        caplog.set_level(logging.ERROR, LOGGER.name)
        logger_crash_maximum_nb_lines[LOGGER.name] = 1
        endpoint = await client_factory()

        await endpoint.sendto(b"request", None)
        while not caplog.records:
            await asyncio.sleep(0.2)

        assert len(caplog.records) == 1
        assert caplog.records[0].levelno == logging.ERROR
        assert caplog.records[0].getMessage() == "RuntimeError: protocol.make_datagram() crashed (caused by SystemError: CRASH)"

    async def test____serve_forever____os_error(
        self,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
        caplog: pytest.LogCaptureFixture,
        logger_crash_maximum_nb_lines: dict[str, int],
    ) -> None:
        caplog.set_level(logging.ERROR, LOGGER.name)
        logger_crash_maximum_nb_lines[LOGGER.name] = 3
        endpoint = await client_factory()

        await endpoint.sendto(b"__os_error__", None)
        await asyncio.sleep(0.2)

        assert len(caplog.records) == 3
        assert caplog.records[1].exc_info is not None
        assert type(caplog.records[1].exc_info[1]) is OSError

    @pytest.mark.parametrize("excgrp", [False, True], ids=lambda p: f"exception_group_raised=={p}")
    async def test____serve_forever____use_of_a_closed_client_in_request_handler(  # In a world where this thing happen
        self,
        excgrp: bool,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
        caplog: pytest.LogCaptureFixture,
        logger_crash_maximum_nb_lines: dict[str, int],
    ) -> None:
        caplog.set_level(logging.WARNING, LOGGER.name)
        logger_crash_maximum_nb_lines[LOGGER.name] = 1
        endpoint = await client_factory()

        if excgrp:
            await endpoint.sendto(b"__closed_client_error_excgrp__", None)
        else:
            await endpoint.sendto(b"__closed_client_error__", None)
        await asyncio.sleep(0.2)

        assert len(caplog.records) == 1
        assert caplog.records[0].levelno == logging.WARNING
        assert caplog.records[0].message.startswith("There have been attempts to do operation on closed client")

    @pytest.mark.parametrize("request_handler", [TimeoutYieldedRequestHandler, TimeoutContextRequestHandler], indirect=True)
    @pytest.mark.parametrize("request_timeout", [0.0, 1.0], ids=lambda p: f"timeout=={p}")
    @pytest.mark.parametrize("timeout_on_third_yield", [False, True], ids=lambda p: f"timeout_on_third_yield=={p}")
    async def test____serve_forever____throw_cancelled_error(
        self,
        request_timeout: float,
        timeout_on_third_yield: bool,
        request_handler: TimeoutYieldedRequestHandler | TimeoutContextRequestHandler,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
    ) -> None:
        request_handler.request_timeout = request_timeout
        request_handler.timeout_on_third_yield = timeout_on_third_yield
        endpoint = await client_factory()

        await endpoint.sendto(b"something", None)
        if timeout_on_third_yield:
            await endpoint.sendto(b"something", None)
            assert (await endpoint.recvfrom())[0] == b"something"

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
        logger_crash_maximum_nb_lines: dict[str, int],
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
    ) -> None:
        caplog.set_level(logging.ERROR, LOGGER.name)
        logger_crash_maximum_nb_lines[LOGGER.name] = 3
        endpoint = await client_factory()

        request_handler.raise_error = True
        await endpoint.sendto(b"something", None)
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.5):
                await endpoint.recvfrom()
        assert len(caplog.records) == 3
        assert caplog.records[1].exc_info is not None
        assert type(caplog.records[1].exc_info[1]) is RandomError
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
    ) -> None:
        request_handler.bypass_refusal = False
        request_handler.refuse_after = refuse_after
        caplog.set_level(logging.ERROR, LOGGER.name)
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
    @pytest.mark.parametrize("ignore_cancellation", [False, True], ids=lambda p: f"ignore_cancellation=={p}")
    async def test____serve_forever____datagram_while_request_handle_is_performed____server_shutdown(
        self,
        server: MyAsyncUnixDatagramServer,
        request_handler: ConcurrencyTestRequestHandler,
        ignore_cancellation: bool,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
        logger_crash_xfail: dict[str, str],
    ) -> None:
        request_handler.sleep_time_before_second_yield = 0.5
        request_handler.ignore_cancellation = ignore_cancellation
        endpoint = await client_factory()
        if ignore_cancellation:
            logger_crash_xfail["easynetwork.lowlevel.api_async.servers.datagram"] = "Cancellation has been ignored."

        await endpoint.sendto(b"something", None)
        await endpoint.sendto(b"hello, world.", None)
        await endpoint.sendto(b"hello, world. new game +", None)
        await asyncio.sleep(0.1)
        async with asyncio.timeout(1):
            await server.shutdown()

    @pytest.mark.parametrize("request_handler", [ConcurrencyTestRequestHandler], indirect=True)
    @pytest.mark.parametrize("recreate_generator", [False, True], ids=lambda p: f"recreate_generator=={p}")
    async def test____serve_forever____too_many_datagrams_while_request_handle_is_performed(
        self,
        recreate_generator: bool,
        request_handler: ConcurrencyTestRequestHandler,
        client_factory: Callable[[], Awaitable[DatagramEndpoint]],
    ) -> None:
        request_handler.sleep_time_before_response = 0.5
        request_handler.recreate_generator = recreate_generator
        endpoint = await client_factory()

        async with asyncio.timeout(5):
            await endpoint.sendto(b"something", None)
            await asyncio.sleep(0.1)
            await endpoint.sendto(b"hello, world.", None)
            for i in range(3):
                await endpoint.sendto(b"something", None)
                await endpoint.sendto(f"hello, world {i+2} times.".encode(), None)
            await endpoint.sendto(b"something", None)
            await asyncio.sleep(0.1)
            request_handler.sleep_time_before_response = None
            await endpoint.sendto(b"hello, world. new game +", None)
            assert (await endpoint.recvfrom())[0] == b"After wait: hello, world."
            assert (await endpoint.recvfrom())[0] == b"After wait: hello, world 2 times."
            assert (await endpoint.recvfrom())[0] == b"After wait: hello, world 3 times."
            assert (await endpoint.recvfrom())[0] == b"After wait: hello, world 4 times."
            assert (await endpoint.recvfrom())[0] == b"After wait: hello, world. new game +"
