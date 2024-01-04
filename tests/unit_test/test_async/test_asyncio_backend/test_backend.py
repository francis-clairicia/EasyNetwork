from __future__ import annotations

import asyncio
import contextvars
from collections.abc import Callable, Coroutine, Sequence
from socket import AF_INET, AF_INET6, AF_UNSPEC, AI_ADDRCONFIG, AI_PASSIVE, IPPROTO_TCP, IPPROTO_UDP, SOCK_DGRAM, SOCK_STREAM
from typing import TYPE_CHECKING, Any, cast

from easynetwork.lowlevel.std_asyncio import AsyncIOBackend
from easynetwork.lowlevel.std_asyncio.stream.listener import (
    AbstractAcceptedSocketFactory,
    AcceptedSocketFactory,
    AcceptedSSLSocketFactory,
)
from easynetwork.lowlevel.std_asyncio.stream.socket import AsyncioTransportStreamSocketAdapter, RawStreamSocketAdapter

import pytest

from ....tools import temporary_task_factory
from ..._utils import partial_eq

if TYPE_CHECKING:
    from unittest.mock import AsyncMock, MagicMock

    from pytest_mock import MockerFixture


class TestAsyncIOBackendSync:
    @pytest.fixture
    @staticmethod
    def backend() -> AsyncIOBackend:
        return AsyncIOBackend()

    @pytest.mark.parametrize("runner_options", [{"loop_factory": asyncio.new_event_loop}, None])
    def test____bootstrap____start_new_runner(
        self,
        runner_options: dict[str, Any] | None,
        backend: AsyncIOBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_asyncio_runner_cls = mocker.patch("asyncio.Runner", side_effect=asyncio.Runner)
        mock_coroutine = mocker.AsyncMock(spec=Coroutine, return_value=mocker.sentinel.Runner_ret_val)
        coro_stub = mocker.stub()
        coro_stub.return_value = mock_coroutine()

        # Act
        ret_val = backend.bootstrap(
            coro_stub,
            mocker.sentinel.arg1,
            mocker.sentinel.arg2,
            mocker.sentinel.arg3,
            runner_options=runner_options,
        )

        # Assert
        if runner_options is None:
            mock_asyncio_runner_cls.assert_called_once_with()
        else:
            mock_asyncio_runner_cls.assert_called_once_with(**runner_options)

        coro_stub.assert_called_once_with(
            mocker.sentinel.arg1,
            mocker.sentinel.arg2,
            mocker.sentinel.arg3,
        )

        mock_coroutine.assert_awaited_once_with()
        assert ret_val is mocker.sentinel.Runner_ret_val


@pytest.mark.asyncio
class TestAsyncIOBackend:
    @pytest.fixture(params=[False, True], ids=lambda boolean: f"use_asyncio_transport=={boolean}")
    @staticmethod
    def use_asyncio_transport(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> bool:
        use_asyncio_transport: bool = bool(getattr(request, "param"))

        if use_asyncio_transport:
            monkeypatch.setenv("EASYNETWORK_HINT_FORCE_USE_ASYNCIO_TRANSPORTS", "1")
        else:
            monkeypatch.delenv("EASYNETWORK_HINT_FORCE_USE_ASYNCIO_TRANSPORTS", raising=False)

        return use_asyncio_transport

    @pytest.fixture
    @staticmethod
    def backend(use_asyncio_transport: bool) -> AsyncIOBackend:
        return AsyncIOBackend()

    @pytest.fixture(params=[("local_address", 12345), None], ids=lambda addr: f"local_address=={addr}")
    @staticmethod
    def local_address(request: Any) -> tuple[str, int] | None:
        return request.param

    @pytest.fixture(params=[("remote_address", 5000)], ids=lambda addr: f"remote_address=={addr}")
    @staticmethod
    def remote_address(request: Any) -> tuple[str, int] | None:
        return request.param

    async def test____use_asyncio_transport____follows_option(
        self,
        backend: AsyncIOBackend,
        use_asyncio_transport: bool,
    ) -> None:
        assert backend.using_asyncio_transports() == use_asyncio_transport

    async def test____get_cancelled_exc_class____returns_asyncio_CancelledError(
        self,
        backend: AsyncIOBackend,
    ) -> None:
        # Arrange

        # Act & Assert
        assert backend.get_cancelled_exc_class() is asyncio.CancelledError

    async def test____current_time____use_event_loop_time(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_loop_time: MagicMock = mocker.patch.object(event_loop, "time", side_effect=event_loop.time)

        # Act
        current_time = backend.current_time()

        # Assert
        mock_loop_time.assert_called_once_with()
        assert current_time > 0

    async def test____sleep____use_asyncio_sleep(
        self,
        backend: AsyncIOBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_sleep: AsyncMock = mocker.patch("asyncio.sleep", new_callable=mocker.async_stub)

        # Act
        await backend.sleep(123456789)

        # Assert
        mock_sleep.assert_awaited_once_with(123456789)

    async def test____ignore_cancellation____wrap_awaitable(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        future = event_loop.create_future()
        future.set_result(mocker.sentinel.ret_val)

        # Act
        ret_val = await backend.ignore_cancellation(future)

        # Assert
        assert ret_val is mocker.sentinel.ret_val

    async def test____ignore_cancellation____create_task_failed(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        awaitable = mocker.async_stub()
        awaitable.return_value = None
        task_factory = mocker.stub()
        exc = Exception("error")
        task_factory.side_effect = exc

        # Act & Assert
        with temporary_task_factory(event_loop, task_factory):
            with pytest.raises(Exception) as exc_info:
                await backend.ignore_cancellation(awaitable())

            assert exc_info.value is exc
            awaitable.assert_not_awaited()

    async def test____ignore_cancellation____not_a_coroutine(
        self,
        backend: AsyncIOBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_asyncio_is_coroutine: MagicMock = mocker.patch("asyncio.iscoroutine", autospec=True, return_value=False)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected an awaitable object$"):
            await backend.ignore_cancellation(mocker.sentinel.coroutine)

        mock_asyncio_is_coroutine.assert_not_called()

    async def test____get_current_task____compute_task_info(
        self,
        backend: AsyncIOBackend,
    ) -> None:
        # Arrange
        current_task = asyncio.current_task()
        assert current_task is not None

        # Act
        task_info = backend.get_current_task()

        # Assert
        assert task_info.id == id(current_task)
        assert task_info.name == current_task.get_name()
        assert task_info.coro is current_task.get_coro()

    @pytest.mark.parametrize("use_asyncio_transport", [True], indirect=True)
    @pytest.mark.parametrize("ssl", [False, True], ids=lambda p: f"ssl=={p}")
    @pytest.mark.parametrize("happy_eyeballs_delay", [None, 42], ids=lambda p: f"happy_eyeballs_delay=={p}")
    async def test____create_tcp_connection____use_asyncio_open_connection(
        self,
        ssl: bool,
        happy_eyeballs_delay: float | None,
        event_loop: asyncio.AbstractEventLoop,
        local_address: tuple[str, int] | None,
        remote_address: tuple[str, int],
        backend: AsyncIOBackend,
        mock_asyncio_stream_reader_factory: Callable[[], MagicMock],
        mock_asyncio_stream_writer_factory: Callable[[], MagicMock],
        mock_ssl_context: MagicMock,
        mock_tcp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_asyncio_reader = mock_asyncio_stream_reader_factory()
        mock_asyncio_writer = mock_asyncio_stream_writer_factory()
        mock_StreamSocketAdapter: MagicMock = mocker.patch(
            "easynetwork.lowlevel.std_asyncio.backend.AsyncioTransportStreamSocketAdapter", return_value=mocker.sentinel.socket
        )
        mock_open_connection: AsyncMock = mocker.patch(
            "asyncio.open_connection",
            new_callable=mocker.AsyncMock,
            return_value=(mock_asyncio_reader, mock_asyncio_writer),
        )
        mock_own_create_connection: AsyncMock = mocker.patch(
            "easynetwork.lowlevel.std_asyncio.backend.create_connection",
            new_callable=mocker.AsyncMock,
            return_value=mock_tcp_socket,
        )

        expected_ssl_kwargs: dict[str, Any] = {}
        if ssl:
            expected_ssl_kwargs = {
                "ssl": mock_ssl_context,
                "server_hostname": "server_hostname",
                "ssl_handshake_timeout": 123456.789,
                "ssl_shutdown_timeout": 9876543.21,
            }
        expected_happy_eyeballs_delay: float = 0.25
        if happy_eyeballs_delay is not None:
            expected_happy_eyeballs_delay = happy_eyeballs_delay

        # Act
        socket: AsyncioTransportStreamSocketAdapter | RawStreamSocketAdapter
        if ssl:
            socket = await backend.create_ssl_over_tcp_connection(
                *remote_address,
                ssl_context=mock_ssl_context,
                server_hostname="server_hostname",
                ssl_handshake_timeout=123456.789,
                ssl_shutdown_timeout=9876543.21,
                happy_eyeballs_delay=happy_eyeballs_delay,
                local_address=local_address,
            )
        else:
            socket = await backend.create_tcp_connection(
                *remote_address,
                happy_eyeballs_delay=happy_eyeballs_delay,
                local_address=local_address,
            )

        # Assert
        mock_own_create_connection.assert_awaited_once_with(
            *remote_address,
            event_loop,
            happy_eyeballs_delay=expected_happy_eyeballs_delay,
            local_address=local_address,
        )
        mock_open_connection.assert_awaited_once_with(
            sock=mock_tcp_socket,
            **expected_ssl_kwargs,
        )
        mock_StreamSocketAdapter.assert_called_once_with(mock_asyncio_reader, mock_asyncio_writer)
        assert socket is mocker.sentinel.socket

    @pytest.mark.parametrize("use_asyncio_transport", [False], indirect=True)
    @pytest.mark.parametrize("happy_eyeballs_delay", [None, 42], ids=lambda p: f"happy_eyeballs_delay=={p}")
    async def test____create_tcp_connection____creates_raw_socket_adapter(
        self,
        event_loop: asyncio.AbstractEventLoop,
        happy_eyeballs_delay: float | None,
        local_address: tuple[str, int] | None,
        remote_address: tuple[str, int],
        backend: AsyncIOBackend,
        mock_tcp_socket: Callable[[], MagicMock],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_RawStreamSocketAdapter: MagicMock = mocker.patch(
            "easynetwork.lowlevel.std_asyncio.backend.RawStreamSocketAdapter", return_value=mocker.sentinel.socket
        )
        mock_asyncio_open_connection: AsyncMock = mocker.patch(
            "asyncio.open_connection",
            new_callable=mocker.AsyncMock,
            side_effect=AssertionError,
        )
        mock_own_create_connection: AsyncMock = mocker.patch(
            "easynetwork.lowlevel.std_asyncio.backend.create_connection",
            new_callable=mocker.AsyncMock,
            return_value=mock_tcp_socket,
        )
        expected_happy_eyeballs_delay: float = 0.25
        if happy_eyeballs_delay is not None:
            expected_happy_eyeballs_delay = happy_eyeballs_delay

        # Act
        socket = await backend.create_tcp_connection(
            *remote_address,
            local_address=local_address,
            happy_eyeballs_delay=happy_eyeballs_delay,
        )

        # Assert
        mock_asyncio_open_connection.assert_not_called()
        mock_own_create_connection.assert_awaited_once_with(
            *remote_address,
            event_loop,
            local_address=local_address,
            happy_eyeballs_delay=expected_happy_eyeballs_delay,
        )
        mock_RawStreamSocketAdapter.assert_called_once_with(mock_tcp_socket, event_loop)
        assert socket is mocker.sentinel.socket

    async def test____create_ssl_over_tcp_connection____use_host_as_server_hostname(
        self,
        event_loop: asyncio.AbstractEventLoop,
        local_address: tuple[str, int] | None,
        remote_address: tuple[str, int],
        backend: AsyncIOBackend,
        mock_asyncio_stream_reader_factory: Callable[[], MagicMock],
        mock_asyncio_stream_writer_factory: Callable[[], MagicMock],
        mock_ssl_context: MagicMock,
        mock_tcp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_asyncio_reader = mock_asyncio_stream_reader_factory()
        mock_asyncio_writer = mock_asyncio_stream_writer_factory()
        mock_StreamSocketAdapter: MagicMock = mocker.patch(
            "easynetwork.lowlevel.std_asyncio.backend.AsyncioTransportStreamSocketAdapter", return_value=mocker.sentinel.socket
        )
        mock_open_connection: AsyncMock = mocker.patch(
            "asyncio.open_connection",
            new_callable=mocker.AsyncMock,
            return_value=(mock_asyncio_reader, mock_asyncio_writer),
        )
        mock_own_create_connection: AsyncMock = mocker.patch(
            "easynetwork.lowlevel.std_asyncio.backend.create_connection",
            new_callable=mocker.AsyncMock,
            return_value=mock_tcp_socket,
        )

        # Act
        socket: AsyncioTransportStreamSocketAdapter | RawStreamSocketAdapter = await backend.create_ssl_over_tcp_connection(
            *remote_address,
            ssl_context=mock_ssl_context,
            server_hostname=None,
            ssl_handshake_timeout=123456.789,
            ssl_shutdown_timeout=9876543.21,
            happy_eyeballs_delay=42,
            local_address=local_address,
        )

        # Assert
        mock_own_create_connection.assert_awaited_once_with(
            *remote_address,
            event_loop,
            happy_eyeballs_delay=42,
            local_address=local_address,
        )
        mock_open_connection.assert_awaited_once_with(
            sock=mock_tcp_socket,
            ssl=mock_ssl_context,
            server_hostname=remote_address[0],
            ssl_handshake_timeout=123456.789,
            ssl_shutdown_timeout=9876543.21,
        )
        mock_StreamSocketAdapter.assert_called_once_with(mock_asyncio_reader, mock_asyncio_writer)
        assert socket is mocker.sentinel.socket

    async def test____create_ssl_over_tcp_connection____invalid_ssl_context_value(
        self,
        local_address: tuple[str, int] | None,
        remote_address: tuple[str, int],
        backend: AsyncIOBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_AsyncioTransportStreamSocketAdapter: MagicMock = mocker.patch(
            "easynetwork.lowlevel.std_asyncio.backend.AsyncioTransportStreamSocketAdapter", side_effect=AssertionError
        )
        mock_asyncio_open_connection: AsyncMock = mocker.patch(
            "asyncio.open_connection",
            new_callable=mocker.AsyncMock,
            side_effect=AssertionError,
        )
        mock_own_create_connection: AsyncMock = mocker.patch(
            "easynetwork.lowlevel.std_asyncio.backend.create_connection",
            new_callable=mocker.AsyncMock,
            side_effect=AssertionError,
        )

        # Act
        with pytest.raises(ValueError, match=r"^Expected a ssl\.SSLContext instance, got True$"):
            await backend.create_ssl_over_tcp_connection(
                *remote_address,
                ssl_context=True,  # type: ignore[arg-type]
                server_hostname="server_hostname",
                ssl_handshake_timeout=123456.789,
                ssl_shutdown_timeout=9876543.21,
                happy_eyeballs_delay=42,
                local_address=local_address,
            )

        # Assert
        mock_own_create_connection.assert_not_called()
        mock_asyncio_open_connection.assert_not_called()
        mock_AsyncioTransportStreamSocketAdapter.assert_not_called()

    @pytest.mark.usefixtures("simulate_no_ssl_module")
    async def test____create_ssl_over_tcp_connection____no_ssl_module(
        self,
        local_address: tuple[str, int] | None,
        remote_address: tuple[str, int],
        backend: AsyncIOBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_AsyncioTransportStreamSocketAdapter: MagicMock = mocker.patch(
            "easynetwork.lowlevel.std_asyncio.backend.AsyncioTransportStreamSocketAdapter", side_effect=AssertionError
        )
        mock_asyncio_open_connection: AsyncMock = mocker.patch(
            "asyncio.open_connection",
            new_callable=mocker.AsyncMock,
            side_effect=AssertionError,
        )
        mock_own_create_connection: AsyncMock = mocker.patch(
            "easynetwork.lowlevel.std_asyncio.backend.create_connection",
            new_callable=mocker.AsyncMock,
            side_effect=AssertionError,
        )

        # Act
        with pytest.raises(RuntimeError, match=r"^stdlib ssl module not available$"):
            await backend.create_ssl_over_tcp_connection(
                *remote_address,
                ssl_context=True,  # type: ignore[arg-type]
                server_hostname="server_hostname",
                ssl_handshake_timeout=123456.789,
                ssl_shutdown_timeout=9876543.21,
                happy_eyeballs_delay=42,
                local_address=local_address,
            )

        # Assert
        mock_own_create_connection.assert_not_called()
        mock_asyncio_open_connection.assert_not_called()
        mock_AsyncioTransportStreamSocketAdapter.assert_not_called()

    async def test____wrap_stream_socket____use_asyncio_open_connection(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
        use_asyncio_transport: bool,
        mock_tcp_socket: MagicMock,
        mock_asyncio_stream_reader_factory: Callable[[], MagicMock],
        mock_asyncio_stream_writer_factory: Callable[[], MagicMock],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_asyncio_reader = mock_asyncio_stream_reader_factory()
        mock_asyncio_writer = mock_asyncio_stream_writer_factory()
        mock_AsyncioTransportStreamSocketAdapter: MagicMock = mocker.patch(
            "easynetwork.lowlevel.std_asyncio.backend.AsyncioTransportStreamSocketAdapter",
            return_value=mocker.sentinel.socket,
        )
        mock_RawStreamSocketAdapter: MagicMock = mocker.patch(
            "easynetwork.lowlevel.std_asyncio.backend.RawStreamSocketAdapter",
            return_value=mocker.sentinel.socket,
        )
        mock_open_connection: AsyncMock = mocker.patch(
            "asyncio.open_connection",
            new_callable=mocker.AsyncMock,
            return_value=(mock_asyncio_reader, mock_asyncio_writer),
        )

        # Act
        socket = await backend.wrap_stream_socket(mock_tcp_socket)

        # Assert
        if use_asyncio_transport:
            mock_open_connection.assert_awaited_once_with(sock=mock_tcp_socket)
            mock_AsyncioTransportStreamSocketAdapter.assert_called_once_with(mock_asyncio_reader, mock_asyncio_writer)
            mock_RawStreamSocketAdapter.assert_not_called()
        else:
            mock_open_connection.assert_not_awaited()
            mock_RawStreamSocketAdapter.assert_called_once_with(mock_tcp_socket, event_loop)
            mock_AsyncioTransportStreamSocketAdapter.assert_not_called()
        assert socket is mocker.sentinel.socket
        mock_tcp_socket.setblocking.assert_called_with(False)

    async def test____wrap_ssl_over_stream_socket____use_asyncio_open_connection(
        self,
        backend: AsyncIOBackend,
        mock_tcp_socket: MagicMock,
        mock_asyncio_stream_reader_factory: Callable[[], MagicMock],
        mock_asyncio_stream_writer_factory: Callable[[], MagicMock],
        mock_ssl_context: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_asyncio_reader = mock_asyncio_stream_reader_factory()
        mock_asyncio_writer = mock_asyncio_stream_writer_factory()
        mock_AsyncioTransportStreamSocketAdapter: MagicMock = mocker.patch(
            "easynetwork.lowlevel.std_asyncio.backend.AsyncioTransportStreamSocketAdapter",
            return_value=mocker.sentinel.socket,
        )
        mock_open_connection: AsyncMock = mocker.patch(
            "asyncio.open_connection",
            new_callable=mocker.AsyncMock,
            return_value=(mock_asyncio_reader, mock_asyncio_writer),
        )

        # Act
        socket = await backend.wrap_ssl_over_stream_socket_client_side(
            mock_tcp_socket,
            ssl_context=mock_ssl_context,
            server_hostname="server_hostname",
            ssl_handshake_timeout=123456.789,
            ssl_shutdown_timeout=9876543.21,
        )

        # Assert
        mock_open_connection.assert_awaited_once_with(
            sock=mock_tcp_socket,
            ssl=mock_ssl_context,
            server_hostname="server_hostname",
            ssl_handshake_timeout=123456.789,
            ssl_shutdown_timeout=9876543.21,
        )
        mock_AsyncioTransportStreamSocketAdapter.assert_called_once_with(mock_asyncio_reader, mock_asyncio_writer)
        assert socket is mocker.sentinel.socket
        mock_tcp_socket.setblocking.assert_called_with(False)

    async def test____wrap_ssl_over_stream_socket____invalid_ssl_context_value(
        self,
        mock_tcp_socket: MagicMock,
        backend: AsyncIOBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_AsyncioTransportStreamSocketAdapter: MagicMock = mocker.patch(
            "easynetwork.lowlevel.std_asyncio.backend.AsyncioTransportStreamSocketAdapter", side_effect=AssertionError
        )
        mock_asyncio_open_connection: AsyncMock = mocker.patch(
            "asyncio.open_connection",
            new_callable=mocker.AsyncMock,
            side_effect=AssertionError,
        )

        # Act
        with pytest.raises(ValueError, match=r"^Expected a ssl\.SSLContext instance, got True$"):
            await backend.wrap_ssl_over_stream_socket_client_side(
                mock_tcp_socket,
                ssl_context=True,  # type: ignore[arg-type]
                server_hostname="server_hostname",
                ssl_handshake_timeout=123456.789,
                ssl_shutdown_timeout=9876543.21,
            )

        # Assert
        mock_asyncio_open_connection.assert_not_called()
        mock_AsyncioTransportStreamSocketAdapter.assert_not_called()

    @pytest.mark.usefixtures("simulate_no_ssl_module")
    async def test____wrap_ssl_over_stream_socket____no_ssl_module(
        self,
        mock_tcp_socket: MagicMock,
        backend: AsyncIOBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_AsyncioTransportStreamSocketAdapter: MagicMock = mocker.patch(
            "easynetwork.lowlevel.std_asyncio.backend.AsyncioTransportStreamSocketAdapter", side_effect=AssertionError
        )
        mock_asyncio_open_connection: AsyncMock = mocker.patch(
            "asyncio.open_connection",
            new_callable=mocker.AsyncMock,
            side_effect=AssertionError,
        )

        # Act
        with pytest.raises(RuntimeError, match=r"^stdlib ssl module not available$"):
            await backend.wrap_ssl_over_stream_socket_client_side(
                mock_tcp_socket,
                ssl_context=True,  # type: ignore[arg-type]
                server_hostname="server_hostname",
                ssl_handshake_timeout=123456.789,
                ssl_shutdown_timeout=9876543.21,
            )

        # Assert
        mock_asyncio_open_connection.assert_not_called()
        mock_AsyncioTransportStreamSocketAdapter.assert_not_called()

    @pytest.mark.parametrize("use_ssl", [pytest.param(False, id="NO_SSL"), pytest.param(True, id="USE_SSL")])
    async def test____create_tcp_listeners____open_listener_sockets(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
        mock_tcp_socket: MagicMock,
        use_ssl: bool,
        mock_ssl_context: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        remote_host, remote_port = "remote_address", 5000
        addrinfo_list = [
            (
                mocker.sentinel.family,
                mocker.sentinel.type,
                mocker.sentinel.proto,
                mocker.sentinel.canonical_name,
                (remote_host, remote_port),
            )
        ]
        mock_getaddrinfo: AsyncMock = cast(
            "AsyncMock",
            mocker.patch.object(
                event_loop,
                "getaddrinfo",
                new_callable=mocker.AsyncMock,
                return_value=addrinfo_list,
            ),
        )
        mock_open_listeners = mocker.patch(
            "easynetwork.lowlevel.std_asyncio.backend.open_listener_sockets_from_getaddrinfo_result",
            return_value=[mock_tcp_socket],
        )
        mock_ListenerSocketAdapter: MagicMock = mocker.patch(
            "easynetwork.lowlevel.std_asyncio.backend.ListenerSocketAdapter", return_value=mocker.sentinel.listener_socket
        )
        expected_factory: AbstractAcceptedSocketFactory[Any]
        if use_ssl:
            expected_factory = AcceptedSSLSocketFactory(
                ssl_context=mock_ssl_context,
                ssl_handshake_timeout=123456.789,
                ssl_shutdown_timeout=9876543.21,
            )
        else:
            expected_factory = AcceptedSocketFactory()

        # Act
        listener_sockets: Sequence[Any]
        if use_ssl:
            listener_sockets = await backend.create_ssl_over_tcp_listeners(
                remote_host,
                remote_port,
                backlog=123456789,
                ssl_context=mock_ssl_context,
                ssl_handshake_timeout=123456.789,
                ssl_shutdown_timeout=9876543.21,
                reuse_port=mocker.sentinel.reuse_port,
            )
        else:
            listener_sockets = await backend.create_tcp_listeners(
                remote_host,
                remote_port,
                backlog=123456789,
                reuse_port=mocker.sentinel.reuse_port,
            )

        # Assert
        mock_getaddrinfo.assert_awaited_once_with(
            remote_host,
            remote_port,
            family=AF_UNSPEC,
            type=SOCK_STREAM,
            proto=0,
            flags=AI_PASSIVE | AI_ADDRCONFIG,
        )
        mock_open_listeners.assert_called_once_with(
            sorted(set(addrinfo_list)),
            backlog=123456789,
            reuse_address=mocker.ANY,  # Determined according to OS
            reuse_port=mocker.sentinel.reuse_port,
        )
        mock_ListenerSocketAdapter.assert_called_once_with(mock_tcp_socket, event_loop, expected_factory)
        assert listener_sockets == [mocker.sentinel.listener_socket]

    @pytest.mark.parametrize("use_ssl", [pytest.param(False, id="NO_SSL"), pytest.param(True, id="USE_SSL")])
    @pytest.mark.parametrize("remote_host", [None, ""], ids=repr)
    async def test____create_tcp_listeners____bind_to_any_interfaces(
        self,
        remote_host: str | None,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
        mock_tcp_socket: MagicMock,
        use_ssl: bool,
        mock_ssl_context: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        remote_port = 5000
        addrinfo_list = [
            (
                AF_INET,
                SOCK_STREAM,
                IPPROTO_TCP,
                "",
                ("0.0.0.0", remote_port),
            ),
            (
                AF_INET6,
                SOCK_STREAM,
                IPPROTO_TCP,
                "",
                ("::", remote_port),
            ),
        ]
        mock_getaddrinfo: AsyncMock = cast(
            "AsyncMock",
            mocker.patch.object(
                event_loop,
                "getaddrinfo",
                new_callable=mocker.AsyncMock,
                return_value=addrinfo_list,
            ),
        )
        mock_open_listeners = mocker.patch(
            "easynetwork.lowlevel.std_asyncio.backend.open_listener_sockets_from_getaddrinfo_result",
            return_value=[mock_tcp_socket, mock_tcp_socket],
        )
        mock_ListenerSocketAdapter: MagicMock = mocker.patch(
            "easynetwork.lowlevel.std_asyncio.backend.ListenerSocketAdapter",
            return_value=mocker.sentinel.listener_socket,
        )
        expected_factory: AbstractAcceptedSocketFactory[Any]
        if use_ssl:
            expected_factory = AcceptedSSLSocketFactory(
                ssl_context=mock_ssl_context,
                ssl_handshake_timeout=123456.789,
                ssl_shutdown_timeout=9876543.21,
            )
        else:
            expected_factory = AcceptedSocketFactory()

        # Act
        listener_sockets: Sequence[Any]
        if use_ssl:
            listener_sockets = await backend.create_ssl_over_tcp_listeners(
                remote_host,
                remote_port,
                backlog=123456789,
                ssl_context=mock_ssl_context,
                ssl_handshake_timeout=123456.789,
                ssl_shutdown_timeout=9876543.21,
                reuse_port=mocker.sentinel.reuse_port,
            )
        else:
            listener_sockets = await backend.create_tcp_listeners(
                remote_host,
                remote_port,
                backlog=123456789,
                reuse_port=mocker.sentinel.reuse_port,
            )

        # Assert
        mock_getaddrinfo.assert_awaited_once_with(
            None,
            remote_port,
            family=AF_UNSPEC,
            type=SOCK_STREAM,
            proto=0,
            flags=AI_PASSIVE | AI_ADDRCONFIG,
        )
        mock_open_listeners.assert_called_once_with(
            sorted(set(addrinfo_list)),
            backlog=123456789,
            reuse_address=mocker.ANY,  # Determined according to OS
            reuse_port=mocker.sentinel.reuse_port,
        )
        assert mock_ListenerSocketAdapter.call_args_list == [
            mocker.call(mock_tcp_socket, event_loop, expected_factory) for _ in range(2)
        ]
        assert listener_sockets == [mocker.sentinel.listener_socket, mocker.sentinel.listener_socket]

    @pytest.mark.parametrize("use_ssl", [pytest.param(False, id="NO_SSL"), pytest.param(True, id="USE_SSL")])
    async def test____create_tcp_listeners____bind_to_several_hosts(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
        mock_tcp_socket: MagicMock,
        use_ssl: bool,
        mock_ssl_context: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        remote_hosts = ["0.0.0.0", "::"]
        remote_port = 5000
        addrinfo_list = [
            (
                AF_INET,
                SOCK_STREAM,
                IPPROTO_TCP,
                "",
                ("0.0.0.0", remote_port),
            ),
            (
                AF_INET6,
                SOCK_STREAM,
                IPPROTO_TCP,
                "",
                ("::", remote_port),
            ),
        ]
        mock_getaddrinfo: AsyncMock = cast(
            "AsyncMock",
            mocker.patch.object(
                event_loop,
                "getaddrinfo",
                new_callable=mocker.AsyncMock,
                side_effect=[[info] for info in addrinfo_list],
            ),
        )
        mock_open_listeners = mocker.patch(
            "easynetwork.lowlevel.std_asyncio.backend.open_listener_sockets_from_getaddrinfo_result",
            return_value=[mock_tcp_socket, mock_tcp_socket],
        )
        mock_ListenerSocketAdapter: MagicMock = mocker.patch(
            "easynetwork.lowlevel.std_asyncio.backend.ListenerSocketAdapter",
            return_value=mocker.sentinel.listener_socket,
        )
        expected_factory: AbstractAcceptedSocketFactory[Any]
        if use_ssl:
            expected_factory = AcceptedSSLSocketFactory(
                ssl_context=mock_ssl_context,
                ssl_handshake_timeout=123456.789,
                ssl_shutdown_timeout=9876543.21,
            )
        else:
            expected_factory = AcceptedSocketFactory()

        # Act
        listener_sockets: Sequence[Any]
        if use_ssl:
            listener_sockets = await backend.create_ssl_over_tcp_listeners(
                remote_hosts,
                remote_port,
                backlog=123456789,
                ssl_context=mock_ssl_context,
                ssl_handshake_timeout=123456.789,
                ssl_shutdown_timeout=9876543.21,
                reuse_port=mocker.sentinel.reuse_port,
            )
        else:
            listener_sockets = await backend.create_tcp_listeners(
                remote_hosts,
                remote_port,
                backlog=123456789,
                reuse_port=mocker.sentinel.reuse_port,
            )

        # Assert
        assert mock_getaddrinfo.await_args_list == [
            mocker.call(
                host,
                remote_port,
                family=AF_UNSPEC,
                type=SOCK_STREAM,
                proto=0,
                flags=AI_PASSIVE | AI_ADDRCONFIG,
            )
            for host in remote_hosts
        ]
        mock_open_listeners.assert_called_once_with(
            sorted(set(addrinfo_list)),
            backlog=123456789,
            reuse_address=mocker.ANY,  # Determined according to OS
            reuse_port=mocker.sentinel.reuse_port,
        )
        assert mock_ListenerSocketAdapter.call_args_list == [
            mocker.call(mock_tcp_socket, event_loop, expected_factory) for _ in range(2)
        ]
        assert listener_sockets == [mocker.sentinel.listener_socket, mocker.sentinel.listener_socket]

    @pytest.mark.parametrize("use_ssl", [pytest.param(False, id="NO_SSL"), pytest.param(True, id="USE_SSL")])
    async def test____create_tcp_listeners____error_getaddrinfo_returns_empty_list(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
        use_ssl: bool,
        mock_ssl_context: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        remote_host = "remote_address"
        remote_port = 5000
        mock_getaddrinfo: AsyncMock = cast(
            "AsyncMock",
            mocker.patch.object(
                event_loop,
                "getaddrinfo",
                new_callable=mocker.AsyncMock,
                return_value=[],
            ),
        )
        mock_open_listeners = mocker.patch(
            "easynetwork.lowlevel.std_asyncio.backend.open_listener_sockets_from_getaddrinfo_result",
            side_effect=AssertionError,
        )
        mock_ListenerSocketAdapter: MagicMock = mocker.patch(
            "easynetwork.lowlevel.std_asyncio.backend.ListenerSocketAdapter",
            side_effect=AssertionError,
        )

        # Act
        with pytest.raises(OSError, match=r"getaddrinfo\('remote_address'\) returned empty list"):
            if use_ssl:
                await backend.create_ssl_over_tcp_listeners(
                    remote_host,
                    remote_port,
                    backlog=123456789,
                    ssl_context=mock_ssl_context,
                    ssl_handshake_timeout=123456.789,
                    ssl_shutdown_timeout=9876543.21,
                    reuse_port=mocker.sentinel.reuse_port,
                )
            else:
                await backend.create_tcp_listeners(
                    remote_host,
                    remote_port,
                    backlog=123456789,
                    reuse_port=mocker.sentinel.reuse_port,
                )

        # Assert
        mock_getaddrinfo.assert_awaited_once_with(
            remote_host,
            remote_port,
            family=AF_UNSPEC,
            type=SOCK_STREAM,
            proto=0,
            flags=AI_PASSIVE | AI_ADDRCONFIG,
        )
        mock_open_listeners.assert_not_called()
        mock_ListenerSocketAdapter.assert_not_called()

    @pytest.mark.parametrize("use_asyncio_transport", [False], indirect=True)
    async def test____create_tcp_listeners____invalid_backlog(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        remote_host = "remote_address"
        remote_port = 5000
        mock_getaddrinfo: AsyncMock = cast(
            "AsyncMock",
            mocker.patch.object(
                event_loop,
                "getaddrinfo",
                new_callable=mocker.AsyncMock,
                return_value=[],
            ),
        )
        mock_open_listeners = mocker.patch(
            "easynetwork.lowlevel.std_asyncio.backend.open_listener_sockets_from_getaddrinfo_result",
            side_effect=AssertionError,
        )
        mock_ListenerSocketAdapter: MagicMock = mocker.patch(
            "easynetwork.lowlevel.std_asyncio.backend.ListenerSocketAdapter",
            side_effect=AssertionError,
        )

        # Act
        with pytest.raises(TypeError, match=r"^backlog: Expected an integer$"):
            await backend.create_tcp_listeners(
                remote_host,
                remote_port,
                backlog=None,  # type: ignore[arg-type]
                reuse_port=mocker.sentinel.reuse_port,
            )

        # Assert
        mock_getaddrinfo.assert_not_called()
        mock_open_listeners.assert_not_called()
        mock_ListenerSocketAdapter.assert_not_called()

    @pytest.mark.parametrize("socket_family", [None, AF_INET, AF_INET6], ids=lambda p: f"family=={p}")
    async def test____create_udp_endpoint____use_loop_create_datagram_endpoint(
        self,
        event_loop: asyncio.AbstractEventLoop,
        local_address: tuple[str, int] | None,
        remote_address: tuple[str, int],
        socket_family: int | None,
        backend: AsyncIOBackend,
        mock_datagram_endpoint_factory: Callable[[], MagicMock],
        use_asyncio_transport: bool,
        mock_udp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        mock_endpoint = mock_datagram_endpoint_factory()
        mock_AsyncioTransportDatagramSocketAdapter: MagicMock = mocker.patch(
            "easynetwork.lowlevel.std_asyncio.backend.AsyncioTransportDatagramSocketAdapter",
            return_value=mocker.sentinel.socket,
        )
        mock_RawDatagramSocketAdapter: MagicMock = mocker.patch(
            "easynetwork.lowlevel.std_asyncio.backend.RawDatagramSocketAdapter",
            return_value=mocker.sentinel.socket,
        )
        mock_create_datagram_endpoint: AsyncMock = mocker.patch(
            "easynetwork.lowlevel.std_asyncio.backend.create_datagram_endpoint",
            new_callable=mocker.AsyncMock,
            return_value=mock_endpoint,
        )
        mock_own_create_connection: AsyncMock = mocker.patch(
            "easynetwork.lowlevel.std_asyncio.backend.create_datagram_connection",
            new_callable=mocker.AsyncMock,
            return_value=mock_udp_socket,
        )

        # Act
        if socket_family is None:
            socket = await backend.create_udp_endpoint(*remote_address, local_address=local_address)
        else:
            socket = await backend.create_udp_endpoint(*remote_address, local_address=local_address, family=socket_family)

        # Assert
        mock_own_create_connection.assert_awaited_once_with(
            *remote_address,
            event_loop,
            local_address=local_address,
            family=AF_UNSPEC if socket_family is None else socket_family,
        )
        if use_asyncio_transport:
            mock_create_datagram_endpoint.assert_awaited_once_with(sock=mock_udp_socket)
            mock_AsyncioTransportDatagramSocketAdapter.assert_called_once_with(mock_endpoint)
            mock_RawDatagramSocketAdapter.assert_not_called()
        else:
            mock_create_datagram_endpoint.assert_not_awaited()
            mock_RawDatagramSocketAdapter.assert_called_once_with(mock_udp_socket, event_loop)
            mock_AsyncioTransportDatagramSocketAdapter.assert_not_called()

        assert socket is mocker.sentinel.socket

    async def test____wrap_connected_datagram_socket____use_loop_create_datagram_endpoint(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
        use_asyncio_transport: bool,
        mock_udp_socket: MagicMock,
        mock_datagram_endpoint_factory: Callable[[], MagicMock],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_endpoint = mock_datagram_endpoint_factory()
        mock_AsyncioTransportDatagramSocketAdapter: MagicMock = mocker.patch(
            "easynetwork.lowlevel.std_asyncio.backend.AsyncioTransportDatagramSocketAdapter",
            return_value=mocker.sentinel.socket,
        )
        mock_RawDatagramSocketAdapter: MagicMock = mocker.patch(
            "easynetwork.lowlevel.std_asyncio.backend.RawDatagramSocketAdapter",
            return_value=mocker.sentinel.socket,
        )
        mock_create_datagram_endpoint: AsyncMock = mocker.patch(
            "easynetwork.lowlevel.std_asyncio.backend.create_datagram_endpoint",
            new_callable=mocker.AsyncMock,
            return_value=mock_endpoint,
        )

        # Act
        socket = await backend.wrap_connected_datagram_socket(mock_udp_socket)

        # Assert
        if use_asyncio_transport:
            mock_create_datagram_endpoint.assert_awaited_once_with(sock=mock_udp_socket)
            mock_AsyncioTransportDatagramSocketAdapter.assert_called_once_with(mock_endpoint)
            mock_RawDatagramSocketAdapter.assert_not_called()
        else:
            mock_create_datagram_endpoint.assert_not_awaited()
            mock_RawDatagramSocketAdapter.assert_called_once_with(mock_udp_socket, event_loop)
            mock_AsyncioTransportDatagramSocketAdapter.assert_not_called()

        assert socket is mocker.sentinel.socket
        mock_udp_socket.setblocking.assert_called_with(False)

    async def test____create_udp_listeners____open_listener_sockets(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
        mock_udp_socket: MagicMock,
        mock_datagram_endpoint_factory: Callable[[], MagicMock],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        remote_host, remote_port = "remote_address", 5000
        addrinfo_list = [
            (
                mocker.sentinel.family,
                mocker.sentinel.type,
                mocker.sentinel.proto,
                mocker.sentinel.canonical_name,
                (remote_host, remote_port),
            )
        ]
        mock_endpoint = mock_datagram_endpoint_factory()
        mock_getaddrinfo: AsyncMock = cast(
            "AsyncMock",
            mocker.patch.object(
                event_loop,
                "getaddrinfo",
                new_callable=mocker.AsyncMock,
                return_value=addrinfo_list,
            ),
        )
        mock_open_listeners = mocker.patch(
            "easynetwork.lowlevel.std_asyncio.backend.open_listener_sockets_from_getaddrinfo_result",
            return_value=[mock_udp_socket],
        )
        mock_create_datagram_endpoint: AsyncMock = mocker.patch(
            "easynetwork.lowlevel.std_asyncio.backend.create_datagram_endpoint",
            new_callable=mocker.AsyncMock,
            return_value=mock_endpoint,
        )
        mock_DatagramListenerSocketAdapter: MagicMock = mocker.patch(
            "easynetwork.lowlevel.std_asyncio.backend.DatagramListenerSocketAdapter",
            return_value=mocker.sentinel.listener_socket,
        )

        # Act
        listener_sockets: Sequence[Any] = await backend.create_udp_listeners(
            remote_host,
            remote_port,
            reuse_port=mocker.sentinel.reuse_port,
        )

        # Assert
        mock_getaddrinfo.assert_awaited_once_with(
            remote_host,
            remote_port,
            family=AF_UNSPEC,
            type=SOCK_DGRAM,
            proto=0,
            flags=AI_PASSIVE | AI_ADDRCONFIG,
        )
        mock_open_listeners.assert_called_once_with(
            sorted(set(addrinfo_list)),
            backlog=None,
            reuse_address=False,
            reuse_port=mocker.sentinel.reuse_port,
        )
        mock_create_datagram_endpoint.assert_awaited_once_with(sock=mock_udp_socket)
        mock_DatagramListenerSocketAdapter.assert_called_once_with(mock_endpoint)
        assert listener_sockets == [mocker.sentinel.listener_socket]

    @pytest.mark.parametrize("remote_host", [None, ""], ids=repr)
    async def test____create_udp_listeners____bind_to_local_interfaces(
        self,
        remote_host: str | None,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
        mock_datagram_endpoint_factory: Callable[[], MagicMock],
        mock_udp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        remote_port = 5000
        addrinfo_list = [
            (
                AF_INET,
                SOCK_DGRAM,
                IPPROTO_UDP,
                "",
                ("127.0.0.1", remote_port),
            ),
            (
                AF_INET6,
                SOCK_DGRAM,
                IPPROTO_UDP,
                "",
                ("::1", remote_port),
            ),
        ]
        mock_endpoint = mock_datagram_endpoint_factory()
        mock_getaddrinfo: AsyncMock = cast(
            "AsyncMock",
            mocker.patch.object(
                event_loop,
                "getaddrinfo",
                new_callable=mocker.AsyncMock,
                return_value=addrinfo_list,
            ),
        )
        mock_open_listeners = mocker.patch(
            "easynetwork.lowlevel.std_asyncio.backend.open_listener_sockets_from_getaddrinfo_result",
            return_value=[mock_udp_socket, mock_udp_socket],
        )
        mock_create_datagram_endpoint: AsyncMock = mocker.patch(
            "easynetwork.lowlevel.std_asyncio.backend.create_datagram_endpoint",
            new_callable=mocker.AsyncMock,
            return_value=mock_endpoint,
        )
        mock_DatagramListenerSocketAdapter: MagicMock = mocker.patch(
            "easynetwork.lowlevel.std_asyncio.backend.DatagramListenerSocketAdapter",
            return_value=mocker.sentinel.listener_socket,
        )

        # Act
        listener_sockets: Sequence[Any] = await backend.create_udp_listeners(
            remote_host,
            remote_port,
            reuse_port=mocker.sentinel.reuse_port,
        )

        # Assert
        mock_getaddrinfo.assert_awaited_once_with(
            None,
            remote_port,
            family=AF_UNSPEC,
            type=SOCK_DGRAM,
            proto=0,
            flags=AI_PASSIVE | AI_ADDRCONFIG,
        )
        mock_open_listeners.assert_called_once_with(
            sorted(set(addrinfo_list)),
            backlog=None,
            reuse_address=False,
            reuse_port=mocker.sentinel.reuse_port,
        )
        assert mock_create_datagram_endpoint.await_args_list == [mocker.call(sock=mock_udp_socket) for _ in range(2)]
        assert mock_DatagramListenerSocketAdapter.call_args_list == [mocker.call(mock_endpoint) for _ in range(2)]
        assert listener_sockets == [mocker.sentinel.listener_socket, mocker.sentinel.listener_socket]

    async def test____create_udp_listeners____bind_to_several_hosts(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
        mock_datagram_endpoint_factory: Callable[[], MagicMock],
        mock_udp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        remote_hosts = ["127.0.0.1", "::1"]
        remote_port = 5000
        addrinfo_list = [
            (
                AF_INET,
                SOCK_DGRAM,
                IPPROTO_UDP,
                "",
                ("127.0.0.1", remote_port),
            ),
            (
                AF_INET6,
                SOCK_DGRAM,
                IPPROTO_UDP,
                "",
                ("::1", remote_port),
            ),
        ]
        mock_endpoint = mock_datagram_endpoint_factory()
        mock_getaddrinfo: AsyncMock = cast(
            "AsyncMock",
            mocker.patch.object(
                event_loop,
                "getaddrinfo",
                new_callable=mocker.AsyncMock,
                return_value=addrinfo_list,
            ),
        )
        mock_open_listeners = mocker.patch(
            "easynetwork.lowlevel.std_asyncio.backend.open_listener_sockets_from_getaddrinfo_result",
            return_value=[mock_udp_socket, mock_udp_socket],
        )
        mock_create_datagram_endpoint: AsyncMock = mocker.patch(
            "easynetwork.lowlevel.std_asyncio.backend.create_datagram_endpoint",
            new_callable=mocker.AsyncMock,
            return_value=mock_endpoint,
        )
        mock_DatagramListenerSocketAdapter: MagicMock = mocker.patch(
            "easynetwork.lowlevel.std_asyncio.backend.DatagramListenerSocketAdapter",
            return_value=mocker.sentinel.listener_socket,
        )

        # Act
        listener_sockets: Sequence[Any] = await backend.create_udp_listeners(
            remote_hosts,
            remote_port,
            reuse_port=mocker.sentinel.reuse_port,
        )

        # Assert
        assert mock_getaddrinfo.await_args_list == [
            mocker.call(
                host,
                remote_port,
                family=AF_UNSPEC,
                type=SOCK_DGRAM,
                proto=0,
                flags=AI_PASSIVE | AI_ADDRCONFIG,
            )
            for host in remote_hosts
        ]
        mock_open_listeners.assert_called_once_with(
            sorted(set(addrinfo_list)),
            backlog=None,
            reuse_address=False,
            reuse_port=mocker.sentinel.reuse_port,
        )
        assert mock_create_datagram_endpoint.await_args_list == [mocker.call(sock=mock_udp_socket) for _ in range(2)]
        assert mock_DatagramListenerSocketAdapter.call_args_list == [mocker.call(mock_endpoint) for _ in range(2)]
        assert listener_sockets == [mocker.sentinel.listener_socket, mocker.sentinel.listener_socket]

    async def test____create_udp_listeners____error_getaddrinfo_returns_empty_list(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        remote_host = "remote_address"
        remote_port = 5000
        mock_getaddrinfo: AsyncMock = cast(
            "AsyncMock",
            mocker.patch.object(
                event_loop,
                "getaddrinfo",
                new_callable=mocker.AsyncMock,
                return_value=[],
            ),
        )
        mock_open_listeners = mocker.patch(
            "easynetwork.lowlevel.std_asyncio.backend.open_listener_sockets_from_getaddrinfo_result",
            side_effect=AssertionError,
        )
        mock_create_datagram_endpoint: AsyncMock = mocker.patch(
            "easynetwork.lowlevel.std_asyncio.backend.create_datagram_endpoint",
            new_callable=mocker.AsyncMock,
            side_effect=AssertionError,
        )
        mock_DatagramListenerSocketAdapter: MagicMock = mocker.patch(
            "easynetwork.lowlevel.std_asyncio.backend.DatagramListenerSocketAdapter",
            side_effect=AssertionError,
        )

        # Act
        with pytest.raises(OSError, match=r"getaddrinfo\('remote_address'\) returned empty list"):
            await backend.create_udp_listeners(
                remote_host,
                remote_port,
                reuse_port=mocker.sentinel.reuse_port,
            )

        # Assert
        mock_getaddrinfo.assert_awaited_once_with(
            remote_host,
            remote_port,
            family=AF_UNSPEC,
            type=SOCK_DGRAM,
            proto=0,
            flags=AI_PASSIVE | AI_ADDRCONFIG,
        )
        mock_open_listeners.assert_not_called()
        mock_create_datagram_endpoint.assert_not_called()
        mock_DatagramListenerSocketAdapter.assert_not_called()

    async def test____create_lock____use_asyncio_Lock_class(
        self,
        backend: AsyncIOBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_Lock = mocker.patch("asyncio.Lock", return_value=mocker.sentinel.lock)

        # Act
        lock = backend.create_lock()

        # Assert
        mock_Lock.assert_called_once_with()
        assert lock is mocker.sentinel.lock

    async def test____create_event____use_asyncio_Event_class(
        self,
        backend: AsyncIOBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_Event = mocker.patch("asyncio.Event", return_value=mocker.sentinel.event)

        # Act
        event = backend.create_event()

        # Assert
        mock_Event.assert_called_once_with()
        assert event is mocker.sentinel.event

    @pytest.mark.parametrize("use_lock", [None, asyncio.Lock])
    async def test____create_condition_var____use_asyncio_Condition_class(
        self,
        use_lock: type[asyncio.Lock] | None,
        backend: AsyncIOBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_lock: MagicMock | None = None if use_lock is None else mocker.NonCallableMagicMock(spec=use_lock)
        mock_Condition = mocker.patch("asyncio.Condition", return_value=mocker.sentinel.condition_var)

        # Act
        condition = backend.create_condition_var(mock_lock)

        # Assert
        mock_Condition.assert_called_once_with(mock_lock)
        assert condition is mocker.sentinel.condition_var

    async def test____run_in_thread____use_loop_run_in_executor(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncIOBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        func_stub = mocker.stub()
        executor_future = event_loop.create_future()
        executor_future.set_result(mocker.sentinel.return_value)
        mock_run_in_executor = mocker.patch.object(event_loop, "run_in_executor", return_value=executor_future)
        mock_context = mocker.NonCallableMagicMock(spec=contextvars.Context)
        mock_copy_context = mocker.patch("contextvars.copy_context", autospec=True, return_value=mock_context)

        # Act
        ret_val = await backend.run_in_thread(
            func_stub,
            mocker.sentinel.arg1,
            mocker.sentinel.arg2,
            kw1=mocker.sentinel.kwargs1,
            kw2=mocker.sentinel.kwargs2,
        )

        # Assert
        mock_copy_context.assert_called_once_with()
        mock_run_in_executor.assert_called_once_with(
            None,
            partial_eq(
                mock_context.run,
                func_stub,
                mocker.sentinel.arg1,
                mocker.sentinel.arg2,
                kw1=mocker.sentinel.kwargs1,
                kw2=mocker.sentinel.kwargs2,
            ),
        )
        func_stub.assert_not_called()
        assert ret_val is mocker.sentinel.return_value

    async def test____create_threads_portal____returns_asyncio_portal(
        self,
        backend: AsyncIOBackend,
    ) -> None:
        # Arrange
        from easynetwork.lowlevel.std_asyncio.threads import ThreadsPortal

        # Act
        threads_portal = backend.create_threads_portal()

        # Assert
        assert isinstance(threads_portal, ThreadsPortal)
