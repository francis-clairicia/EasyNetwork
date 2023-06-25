# -*- coding: utf-8 -*-

from __future__ import annotations

import asyncio
import contextlib
import contextvars
from typing import TYPE_CHECKING, Any, Callable, Sequence, cast

from easynetwork.api_async.backend.abc import AbstractAsyncStreamSocketAdapter
from easynetwork_asyncio import AsyncioBackend

import pytest

from ..._utils import partial_eq

if TYPE_CHECKING:
    from unittest.mock import AsyncMock, MagicMock

    from pytest_mock import MockerFixture


@pytest.mark.asyncio
class TestAsyncIOBackend:
    @pytest.fixture(params=[False, True], ids=lambda boolean: f"use_asyncio_transport=={boolean}")
    @staticmethod
    def use_asyncio_transport(request: Any) -> bool:
        return request.param

    @pytest.fixture
    @staticmethod
    def backend(use_asyncio_transport: bool) -> AsyncioBackend:
        return AsyncioBackend(transport=use_asyncio_transport)

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
        backend: AsyncioBackend,
        use_asyncio_transport: bool,
    ) -> None:
        assert backend.use_asyncio_transport() == use_asyncio_transport

    @pytest.mark.parametrize("cancel_shielded", [False, True], ids=lambda b: f"cancel_shielded=={b}")
    async def test____coro_yield____use_asyncio_sleep(
        self,
        cancel_shielded: bool,
        backend: AsyncioBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_sleep: AsyncMock = mocker.patch("asyncio.sleep", new_callable=mocker.async_stub)

        # Act
        if cancel_shielded:
            await backend.cancel_shielded_coro_yield()
        else:
            await backend.coro_yield()

        # Assert
        mock_sleep.assert_awaited_once_with(0)

    async def test____get_cancelled_exc_class____returns_asyncio_CancelledError(
        self,
        backend: AsyncioBackend,
    ) -> None:
        # Arrange

        # Act & Assert
        assert backend.get_cancelled_exc_class() is asyncio.CancelledError

    async def test____current_time____use_event_loop_time(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncioBackend,
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
        backend: AsyncioBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_sleep: AsyncMock = mocker.patch("asyncio.sleep", new_callable=mocker.async_stub)

        # Act
        await backend.sleep(123456789)

        # Assert
        mock_sleep.assert_awaited_once_with(123456789)

    @pytest.mark.parametrize("use_asyncio_transport", [True], indirect=True)
    @pytest.mark.parametrize("ssl", [False, True], ids=lambda p: f"ssl=={p}")
    async def test____create_tcp_connection____use_asyncio_open_connection(
        self,
        ssl: bool,
        local_address: tuple[str, int] | None,
        remote_address: tuple[str, int],
        backend: AsyncioBackend,
        mock_asyncio_stream_reader_factory: Callable[[], MagicMock],
        mock_asyncio_stream_writer_factory: Callable[[], MagicMock],
        mock_ssl_context: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from easynetwork.tools.socket import MAX_STREAM_BUFSIZE

        mock_asyncio_reader = mock_asyncio_stream_reader_factory()
        mock_asyncio_writer = mock_asyncio_stream_writer_factory()
        mock_StreamSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.backend.AsyncioTransportStreamSocketAdapter", return_value=mocker.sentinel.socket
        )
        mock_open_connection: AsyncMock = mocker.patch(
            "asyncio.open_connection",
            new_callable=mocker.AsyncMock,
            return_value=(mock_asyncio_reader, mock_asyncio_writer),
        )

        expected_ssl_kwargs: dict[str, Any] = {}
        if ssl:
            expected_ssl_kwargs = {
                "ssl": mock_ssl_context,
                "server_hostname": "server_hostname",
                "ssl_handshake_timeout": 123456.789,
                "ssl_shutdown_timeout": 9876543.21,
            }

        # Act
        socket: AbstractAsyncStreamSocketAdapter
        if ssl:
            socket = await backend.create_ssl_over_tcp_connection(
                *remote_address,
                ssl_context=mock_ssl_context,
                server_hostname="server_hostname",
                ssl_handshake_timeout=123456.789,
                ssl_shutdown_timeout=9876543.21,
                happy_eyeballs_delay=42,
                local_address=local_address,
            )
        else:
            socket = await backend.create_tcp_connection(
                *remote_address,
                happy_eyeballs_delay=42,
                local_address=local_address,
            )

        # Assert
        mock_open_connection.assert_awaited_once_with(
            *remote_address,
            **expected_ssl_kwargs,
            happy_eyeballs_delay=42,
            local_addr=local_address,
            limit=MAX_STREAM_BUFSIZE,
        )
        mock_StreamSocketAdapter.assert_called_once_with(mock_asyncio_reader, mock_asyncio_writer)
        assert socket is mocker.sentinel.socket

    @pytest.mark.parametrize("use_asyncio_transport", [True], indirect=True)
    @pytest.mark.parametrize("ssl", [False, True], ids=lambda p: f"ssl=={p}")
    async def test____create_tcp_connection____use_asyncio_open_connection____no_happy_eyeballs_delay(
        self,
        ssl: bool,
        local_address: tuple[str, int] | None,
        remote_address: tuple[str, int],
        backend: AsyncioBackend,
        mock_asyncio_stream_reader_factory: Callable[[], MagicMock],
        mock_asyncio_stream_writer_factory: Callable[[], MagicMock],
        mock_ssl_context: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from easynetwork.tools.socket import MAX_STREAM_BUFSIZE

        mocker.patch("easynetwork_asyncio.backend.AsyncioTransportStreamSocketAdapter", return_value=mocker.sentinel.socket)
        mock_open_connection: AsyncMock = mocker.patch(
            "asyncio.open_connection",
            new_callable=mocker.AsyncMock,
            return_value=(mock_asyncio_stream_reader_factory(), mock_asyncio_stream_writer_factory()),
        )
        mocker.patch("asyncio.get_running_loop", return_value=mocker.NonCallableMagicMock(spec=asyncio.AbstractEventLoop))
        expected_ssl_kwargs: dict[str, Any] = {}
        if ssl:
            expected_ssl_kwargs = {
                "ssl": mock_ssl_context,
                "server_hostname": "server_hostname",
                "ssl_handshake_timeout": 123456.789,
                "ssl_shutdown_timeout": 9876543.21,
            }

        # Act
        if ssl:
            await backend.create_ssl_over_tcp_connection(
                *remote_address,
                ssl_context=mock_ssl_context,
                server_hostname="server_hostname",
                ssl_handshake_timeout=123456.789,
                ssl_shutdown_timeout=9876543.21,
                happy_eyeballs_delay=None,
                local_address=local_address,
            )
        else:
            await backend.create_tcp_connection(
                *remote_address,
                happy_eyeballs_delay=None,
                local_address=local_address,
            )

        # Assert
        mock_open_connection.assert_awaited_once_with(
            *remote_address,
            **expected_ssl_kwargs,
            local_addr=local_address,
            limit=MAX_STREAM_BUFSIZE,
        )

    @pytest.mark.parametrize("use_asyncio_transport", [True], indirect=True)
    @pytest.mark.parametrize("ssl", [False, True], ids=lambda p: f"ssl=={p}")
    async def test____create_tcp_connection____use_asyncio_open_connection____happy_eyeballs_delay_default_value_for_asyncio_implementation(
        self,
        ssl: bool,
        local_address: tuple[str, int] | None,
        remote_address: tuple[str, int],
        backend: AsyncioBackend,
        mock_asyncio_stream_reader_factory: Callable[[], MagicMock],
        mock_asyncio_stream_writer_factory: Callable[[], MagicMock],
        mock_ssl_context: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from easynetwork.tools.socket import MAX_STREAM_BUFSIZE

        mocker.patch("easynetwork_asyncio.backend.AsyncioTransportStreamSocketAdapter", return_value=mocker.sentinel.socket)
        mock_open_connection: AsyncMock = mocker.patch(
            "asyncio.open_connection",
            new_callable=mocker.AsyncMock,
            return_value=(mock_asyncio_stream_reader_factory(), mock_asyncio_stream_writer_factory()),
        )
        mocker.patch("asyncio.get_running_loop", return_value=mocker.NonCallableMagicMock(spec=asyncio.base_events.BaseEventLoop))
        expected_ssl_kwargs: dict[str, Any] = {}
        if ssl:
            expected_ssl_kwargs = {
                "ssl": mock_ssl_context,
                "server_hostname": "server_hostname",
                "ssl_handshake_timeout": 123456.789,
                "ssl_shutdown_timeout": 9876543.21,
            }

        # Act
        if ssl:
            await backend.create_ssl_over_tcp_connection(
                *remote_address,
                ssl_context=mock_ssl_context,
                server_hostname="server_hostname",
                ssl_handshake_timeout=123456.789,
                ssl_shutdown_timeout=9876543.21,
                happy_eyeballs_delay=None,
                local_address=local_address,
            )
        else:
            await backend.create_tcp_connection(
                *remote_address,
                happy_eyeballs_delay=None,
                local_address=local_address,
            )

        # Assert
        mock_open_connection.assert_awaited_once_with(
            *remote_address,
            **expected_ssl_kwargs,
            local_addr=local_address,
            happy_eyeballs_delay=0.25,
            limit=MAX_STREAM_BUFSIZE,
        )

    @pytest.mark.parametrize("use_asyncio_transport", [False], indirect=True)
    async def test____create_tcp_connection____creates_raw_socket_adapter(
        self,
        event_loop: asyncio.AbstractEventLoop,
        local_address: tuple[str, int] | None,
        remote_address: tuple[str, int],
        backend: AsyncioBackend,
        mock_tcp_socket: Callable[[], MagicMock],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_RawStreamSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.backend.RawStreamSocketAdapter", return_value=mocker.sentinel.socket
        )
        mock_asyncio_open_connection: AsyncMock = mocker.patch(
            "asyncio.open_connection",
            new_callable=mocker.AsyncMock,
            side_effect=AssertionError,
        )
        mock_own_create_connection: AsyncMock = mocker.patch(
            "easynetwork_asyncio.backend.create_connection",
            new_callable=mocker.AsyncMock,
            return_value=mock_tcp_socket,
        )

        # Act
        socket = await backend.create_tcp_connection(
            *remote_address,
            local_address=local_address,
        )

        # Assert
        mock_asyncio_open_connection.assert_not_called()
        mock_own_create_connection.assert_awaited_once_with(
            *remote_address,
            event_loop,
            local_address=local_address,
        )
        mock_RawStreamSocketAdapter.assert_called_once_with(mock_tcp_socket, event_loop)
        assert socket is mocker.sentinel.socket

    @pytest.mark.parametrize("use_asyncio_transport", [False], indirect=True)
    async def test____create_tcp_connection____happy_eyeballs_delay_not_supported(
        self,
        local_address: tuple[str, int] | None,
        remote_address: tuple[str, int],
        backend: AsyncioBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_RawStreamSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.backend.RawStreamSocketAdapter", side_effect=AssertionError
        )
        mock_asyncio_open_connection: AsyncMock = mocker.patch(
            "asyncio.open_connection",
            new_callable=mocker.AsyncMock,
            side_effect=AssertionError,
        )
        mock_own_create_connection: AsyncMock = mocker.patch(
            "easynetwork_asyncio.backend.create_connection",
            new_callable=mocker.AsyncMock,
            side_effect=AssertionError,
        )

        # Act
        with pytest.raises(ValueError, match=r"^'happy_eyeballs_delay' option not supported with transport=False$"):
            await backend.create_tcp_connection(
                *remote_address,
                happy_eyeballs_delay=42,
                local_address=local_address,
            )

        # Assert
        mock_asyncio_open_connection.assert_not_called()
        mock_own_create_connection.assert_not_called()
        mock_RawStreamSocketAdapter.assert_not_called()

    @pytest.mark.parametrize("use_asyncio_transport", [False], indirect=True)
    async def test____create_ssl_over_tcp_connection____ssl_not_supported(
        self,
        local_address: tuple[str, int] | None,
        remote_address: tuple[str, int],
        backend: AsyncioBackend,
        mock_ssl_context: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_AsyncioTransportStreamSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.backend.AsyncioTransportStreamSocketAdapter", side_effect=AssertionError
        )
        mock_RawStreamSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.backend.RawStreamSocketAdapter", side_effect=AssertionError
        )
        mock_asyncio_open_connection: AsyncMock = mocker.patch(
            "asyncio.open_connection",
            new_callable=mocker.AsyncMock,
            side_effect=AssertionError,
        )
        mock_own_create_connection: AsyncMock = mocker.patch(
            "easynetwork_asyncio.backend.create_connection",
            new_callable=mocker.AsyncMock,
            side_effect=AssertionError,
        )

        # Act
        with pytest.raises(ValueError, match=r"^SSL\/TLS not supported with transport=False$"):
            await backend.create_ssl_over_tcp_connection(
                *remote_address,
                ssl_context=mock_ssl_context,
                server_hostname="server_hostname",
                ssl_handshake_timeout=123456.789,
                ssl_shutdown_timeout=9876543.21,
                happy_eyeballs_delay=42,
                local_address=local_address,
            )

        # Assert
        mock_asyncio_open_connection.assert_not_called()
        mock_own_create_connection.assert_not_called()
        mock_RawStreamSocketAdapter.assert_not_called()
        mock_AsyncioTransportStreamSocketAdapter.assert_not_called()

    @pytest.mark.parametrize("use_asyncio_transport", [True], indirect=True)
    async def test____create_ssl_over_tcp_connection____invalid_ssl_context_value(
        self,
        local_address: tuple[str, int] | None,
        remote_address: tuple[str, int],
        backend: AsyncioBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_AsyncioTransportStreamSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.backend.AsyncioTransportStreamSocketAdapter", side_effect=AssertionError
        )
        mock_asyncio_open_connection: AsyncMock = mocker.patch(
            "asyncio.open_connection",
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
        mock_asyncio_open_connection.assert_not_called()
        mock_AsyncioTransportStreamSocketAdapter.assert_not_called()

    @pytest.mark.usefixtures("simulate_no_ssl_module")
    @pytest.mark.parametrize("use_asyncio_transport", [True], indirect=True)
    async def test____create_ssl_over_tcp_connection____no_ssl_module(
        self,
        local_address: tuple[str, int] | None,
        remote_address: tuple[str, int],
        backend: AsyncioBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_AsyncioTransportStreamSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.backend.AsyncioTransportStreamSocketAdapter", side_effect=AssertionError
        )
        mock_asyncio_open_connection: AsyncMock = mocker.patch(
            "asyncio.open_connection",
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
        mock_asyncio_open_connection.assert_not_called()
        mock_AsyncioTransportStreamSocketAdapter.assert_not_called()

    async def test____wrap_tcp_client_socket____use_asyncio_open_connection(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncioBackend,
        use_asyncio_transport: bool,
        mock_tcp_socket: MagicMock,
        mock_asyncio_stream_reader_factory: Callable[[], MagicMock],
        mock_asyncio_stream_writer_factory: Callable[[], MagicMock],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from easynetwork.tools.socket import MAX_STREAM_BUFSIZE

        mock_asyncio_reader = mock_asyncio_stream_reader_factory()
        mock_asyncio_writer = mock_asyncio_stream_writer_factory()
        mock_AsyncioTransportStreamSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.backend.AsyncioTransportStreamSocketAdapter",
            return_value=mocker.sentinel.socket,
        )
        mock_RawStreamSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.backend.RawStreamSocketAdapter",
            return_value=mocker.sentinel.socket,
        )
        mock_open_connection: AsyncMock = mocker.patch(
            "asyncio.open_connection",
            new_callable=mocker.AsyncMock,
            return_value=(mock_asyncio_reader, mock_asyncio_writer),
        )

        # Act
        socket = await backend.wrap_tcp_client_socket(mock_tcp_socket)

        # Assert
        if use_asyncio_transport:
            mock_open_connection.assert_awaited_once_with(
                sock=mock_tcp_socket,
                limit=MAX_STREAM_BUFSIZE,
            )
            mock_AsyncioTransportStreamSocketAdapter.assert_called_once_with(mock_asyncio_reader, mock_asyncio_writer)
            mock_RawStreamSocketAdapter.assert_not_called()
        else:
            mock_open_connection.assert_not_awaited()
            mock_RawStreamSocketAdapter.assert_called_once_with(mock_tcp_socket, event_loop)
            mock_AsyncioTransportStreamSocketAdapter.assert_not_called()
        assert socket is mocker.sentinel.socket
        mock_tcp_socket.setblocking.assert_called_with(False)

    async def test____wrap_ssl_over_tcp_client_socket____use_asyncio_open_connection(
        self,
        backend: AsyncioBackend,
        use_asyncio_transport: bool,
        mock_tcp_socket: MagicMock,
        mock_asyncio_stream_reader_factory: Callable[[], MagicMock],
        mock_asyncio_stream_writer_factory: Callable[[], MagicMock],
        mock_ssl_context: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from easynetwork.tools.socket import MAX_STREAM_BUFSIZE

        mock_asyncio_reader = mock_asyncio_stream_reader_factory()
        mock_asyncio_writer = mock_asyncio_stream_writer_factory()
        mock_AsyncioTransportStreamSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.backend.AsyncioTransportStreamSocketAdapter",
            return_value=mocker.sentinel.socket,
        )
        mock_open_connection: AsyncMock = mocker.patch(
            "asyncio.open_connection",
            new_callable=mocker.AsyncMock,
            return_value=(mock_asyncio_reader, mock_asyncio_writer),
        )

        # Act
        with (
            pytest.raises(ValueError, match=r"^SSL\/TLS not supported with transport=False$")
            if not use_asyncio_transport
            else contextlib.nullcontext()
        ):
            socket = await backend.wrap_ssl_over_tcp_client_socket(
                mock_tcp_socket,
                ssl_context=mock_ssl_context,
                server_hostname="server_hostname",
                ssl_handshake_timeout=123456.789,
                ssl_shutdown_timeout=9876543.21,
            )

        # Assert
        if use_asyncio_transport:
            mock_open_connection.assert_awaited_once_with(
                sock=mock_tcp_socket,
                ssl=mock_ssl_context,
                server_hostname="server_hostname",
                ssl_handshake_timeout=123456.789,
                ssl_shutdown_timeout=9876543.21,
                limit=MAX_STREAM_BUFSIZE,
            )
            mock_AsyncioTransportStreamSocketAdapter.assert_called_once_with(mock_asyncio_reader, mock_asyncio_writer)
            assert socket is mocker.sentinel.socket
            mock_tcp_socket.setblocking.assert_called_with(False)
        else:
            mock_open_connection.assert_not_awaited()
            mock_AsyncioTransportStreamSocketAdapter.assert_not_called()
            mock_tcp_socket.setblocking.assert_not_called()

    @pytest.mark.parametrize("use_asyncio_transport", [False], indirect=True)
    async def test____wrap_ssl_over_tcp_client_socket____ssl_not_supported(
        self,
        mock_tcp_socket: MagicMock,
        backend: AsyncioBackend,
        mock_ssl_context: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_AsyncioTransportStreamSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.backend.AsyncioTransportStreamSocketAdapter", side_effect=AssertionError
        )
        mock_RawStreamSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.backend.RawStreamSocketAdapter", side_effect=AssertionError
        )
        mock_asyncio_open_connection: AsyncMock = mocker.patch(
            "asyncio.open_connection",
            new_callable=mocker.AsyncMock,
            side_effect=AssertionError,
        )
        mock_own_create_connection: AsyncMock = mocker.patch(
            "easynetwork_asyncio.backend.create_connection",
            new_callable=mocker.AsyncMock,
            side_effect=AssertionError,
        )

        # Act
        with pytest.raises(ValueError, match=r"^SSL\/TLS not supported with transport=False$"):
            await backend.wrap_ssl_over_tcp_client_socket(
                mock_tcp_socket,
                ssl_context=mock_ssl_context,
                server_hostname="server_hostname",
                ssl_handshake_timeout=123456.789,
                ssl_shutdown_timeout=9876543.21,
            )

        # Assert
        mock_asyncio_open_connection.assert_not_called()
        mock_own_create_connection.assert_not_called()
        mock_RawStreamSocketAdapter.assert_not_called()
        mock_AsyncioTransportStreamSocketAdapter.assert_not_called()

    @pytest.mark.parametrize("use_asyncio_transport", [True], indirect=True)
    async def test____wrap_ssl_over_tcp_client_socket____invalid_ssl_context_value(
        self,
        mock_tcp_socket: MagicMock,
        backend: AsyncioBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_AsyncioTransportStreamSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.backend.AsyncioTransportStreamSocketAdapter", side_effect=AssertionError
        )
        mock_asyncio_open_connection: AsyncMock = mocker.patch(
            "asyncio.open_connection",
            new_callable=mocker.AsyncMock,
            side_effect=AssertionError,
        )

        # Act
        with pytest.raises(ValueError, match=r"^Expected a ssl\.SSLContext instance, got True$"):
            await backend.wrap_ssl_over_tcp_client_socket(
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
    @pytest.mark.parametrize("use_asyncio_transport", [True], indirect=True)
    async def test____wrap_ssl_over_tcp_client_socket____no_ssl_module(
        self,
        mock_tcp_socket: MagicMock,
        backend: AsyncioBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_AsyncioTransportStreamSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.backend.AsyncioTransportStreamSocketAdapter", side_effect=AssertionError
        )
        mock_asyncio_open_connection: AsyncMock = mocker.patch(
            "asyncio.open_connection",
            new_callable=mocker.AsyncMock,
            side_effect=AssertionError,
        )

        # Act
        with pytest.raises(RuntimeError, match=r"^stdlib ssl module not available$"):
            await backend.wrap_ssl_over_tcp_client_socket(
                mock_tcp_socket,
                ssl_context=True,  # type: ignore[arg-type]
                server_hostname="server_hostname",
                ssl_handshake_timeout=123456.789,
                ssl_shutdown_timeout=9876543.21,
            )

        # Assert
        mock_asyncio_open_connection.assert_not_called()
        mock_AsyncioTransportStreamSocketAdapter.assert_not_called()

    @pytest.mark.parametrize(
        ["use_ssl", "use_asyncio_transport"],
        [
            pytest.param(False, False, id="NO_SSL-use_asyncio_transport==False"),
            pytest.param(False, True, id="NO_SSL-use_asyncio_transport==True"),
            pytest.param(True, True, id="USE_SSL"),
        ],
        indirect=["use_asyncio_transport"],
    )
    async def test____create_tcp_listeners____open_listener_sockets(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncioBackend,
        use_asyncio_transport: bool,
        mock_tcp_socket: MagicMock,
        use_ssl: bool,
        mock_ssl_context: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from socket import AF_UNSPEC, AI_PASSIVE, SOCK_STREAM

        from easynetwork_asyncio.stream.listener import AcceptedSocket, AcceptedSSLSocket

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
            "easynetwork_asyncio.backend.open_listener_sockets_from_getaddrinfo_result",
            return_value=[mock_tcp_socket],
        )
        mock_ListenerSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.backend.ListenerSocketAdapter", return_value=mocker.sentinel.listener_socket
        )
        expected_factory: partial_eq
        if use_ssl:
            expected_factory = partial_eq(
                AcceptedSSLSocket,
                ssl_context=mock_ssl_context,
                ssl_handshake_timeout=123456.789,
                ssl_shutdown_timeout=9876543.21,
            )
        else:
            expected_factory = partial_eq(
                AcceptedSocket,
                use_asyncio_transport=use_asyncio_transport,
            )

        # Act
        listener_sockets: Sequence[Any]
        if use_ssl:
            listener_sockets = await backend.create_ssl_over_tcp_listeners(
                remote_host,
                remote_port,
                mocker.sentinel.backlog,
                ssl_context=mock_ssl_context,
                ssl_handshake_timeout=123456.789,
                ssl_shutdown_timeout=9876543.21,
                reuse_port=mocker.sentinel.reuse_port,
            )
        else:
            listener_sockets = await backend.create_tcp_listeners(
                remote_host,
                remote_port,
                mocker.sentinel.backlog,
                reuse_port=mocker.sentinel.reuse_port,
            )

        # Assert
        mock_getaddrinfo.assert_awaited_once_with(
            remote_host,
            remote_port,
            family=AF_UNSPEC,
            type=SOCK_STREAM,
            proto=0,
            flags=AI_PASSIVE,
        )
        mock_open_listeners.assert_called_once_with(
            set(addrinfo_list),
            backlog=mocker.sentinel.backlog,
            reuse_address=mocker.ANY,  # Determined according to OS
            reuse_port=mocker.sentinel.reuse_port,
        )
        mock_ListenerSocketAdapter.assert_called_once_with(mock_tcp_socket, event_loop, expected_factory)
        assert listener_sockets == [mocker.sentinel.listener_socket]

    @pytest.mark.parametrize(
        ["use_ssl", "use_asyncio_transport"],
        [
            pytest.param(False, False, id="NO_SSL-use_asyncio_transport==False"),
            pytest.param(False, True, id="NO_SSL-use_asyncio_transport==True"),
            pytest.param(True, True, id="USE_SSL"),
        ],
        indirect=["use_asyncio_transport"],
    )
    @pytest.mark.parametrize("remote_host", [None, ""], ids=repr)
    async def test____create_tcp_listeners____bind_on_any_interfaces(
        self,
        remote_host: str,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncioBackend,
        use_asyncio_transport: bool,
        mock_tcp_socket: MagicMock,
        use_ssl: bool,
        mock_ssl_context: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from socket import AF_INET, AF_INET6, AF_UNSPEC, AI_PASSIVE, IPPROTO_TCP, SOCK_STREAM

        from easynetwork_asyncio.stream.listener import AcceptedSocket, AcceptedSSLSocket

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
            "easynetwork_asyncio.backend.open_listener_sockets_from_getaddrinfo_result",
            return_value=[mock_tcp_socket, mock_tcp_socket],
        )
        mock_ListenerSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.backend.ListenerSocketAdapter",
            return_value=mocker.sentinel.listener_socket,
        )
        expected_factory: partial_eq
        if use_ssl:
            expected_factory = partial_eq(
                AcceptedSSLSocket,
                ssl_context=mock_ssl_context,
                ssl_handshake_timeout=123456.789,
                ssl_shutdown_timeout=9876543.21,
            )
        else:
            expected_factory = partial_eq(
                AcceptedSocket,
                use_asyncio_transport=use_asyncio_transport,
            )

        # Act
        listener_sockets: Sequence[Any]
        if use_ssl:
            listener_sockets = await backend.create_ssl_over_tcp_listeners(
                remote_host,
                remote_port,
                mocker.sentinel.backlog,
                ssl_context=mock_ssl_context,
                ssl_handshake_timeout=123456.789,
                ssl_shutdown_timeout=9876543.21,
                reuse_port=mocker.sentinel.reuse_port,
            )
        else:
            listener_sockets = await backend.create_tcp_listeners(
                remote_host,
                remote_port,
                mocker.sentinel.backlog,
                reuse_port=mocker.sentinel.reuse_port,
            )

        # Assert
        mock_getaddrinfo.assert_awaited_once_with(
            None,
            remote_port,
            family=AF_UNSPEC,
            type=SOCK_STREAM,
            proto=0,
            flags=AI_PASSIVE,
        )
        mock_open_listeners.assert_called_once_with(
            set(addrinfo_list),
            backlog=mocker.sentinel.backlog,
            reuse_address=mocker.ANY,  # Determined according to OS
            reuse_port=mocker.sentinel.reuse_port,
        )
        assert mock_ListenerSocketAdapter.mock_calls == [
            mocker.call(mock_tcp_socket, event_loop, expected_factory) for _ in range(2)
        ]
        assert listener_sockets == [mocker.sentinel.listener_socket, mocker.sentinel.listener_socket]

    @pytest.mark.parametrize(
        ["use_ssl", "use_asyncio_transport"],
        [
            pytest.param(False, False, id="NO_SSL-use_asyncio_transport==False"),
            pytest.param(False, True, id="NO_SSL-use_asyncio_transport==True"),
            pytest.param(True, True, id="USE_SSL"),
        ],
        indirect=["use_asyncio_transport"],
    )
    async def test____create_tcp_listeners____bind_on_several_hosts(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncioBackend,
        use_asyncio_transport: bool,
        mock_tcp_socket: MagicMock,
        use_ssl: bool,
        mock_ssl_context: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from socket import AF_INET, AF_INET6, AF_UNSPEC, AI_PASSIVE, IPPROTO_TCP, SOCK_STREAM

        from easynetwork_asyncio.stream.listener import AcceptedSocket, AcceptedSSLSocket

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
            "easynetwork_asyncio.backend.open_listener_sockets_from_getaddrinfo_result",
            return_value=[mock_tcp_socket, mock_tcp_socket],
        )
        mock_ListenerSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.backend.ListenerSocketAdapter",
            return_value=mocker.sentinel.listener_socket,
        )
        expected_factory: partial_eq
        if use_ssl:
            expected_factory = partial_eq(
                AcceptedSSLSocket,
                ssl_context=mock_ssl_context,
                ssl_handshake_timeout=123456.789,
                ssl_shutdown_timeout=9876543.21,
            )
        else:
            expected_factory = partial_eq(
                AcceptedSocket,
                use_asyncio_transport=use_asyncio_transport,
            )

        # Act
        listener_sockets: Sequence[Any]
        if use_ssl:
            listener_sockets = await backend.create_ssl_over_tcp_listeners(
                remote_hosts,
                remote_port,
                mocker.sentinel.backlog,
                ssl_context=mock_ssl_context,
                ssl_handshake_timeout=123456.789,
                ssl_shutdown_timeout=9876543.21,
                reuse_port=mocker.sentinel.reuse_port,
            )
        else:
            listener_sockets = await backend.create_tcp_listeners(
                remote_hosts,
                remote_port,
                mocker.sentinel.backlog,
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
                flags=AI_PASSIVE,
            )
            for host in remote_hosts
        ]
        mock_open_listeners.assert_called_once_with(
            set(addrinfo_list),
            backlog=mocker.sentinel.backlog,
            reuse_address=mocker.ANY,  # Determined according to OS
            reuse_port=mocker.sentinel.reuse_port,
        )
        assert mock_ListenerSocketAdapter.mock_calls == [
            mocker.call(mock_tcp_socket, event_loop, expected_factory) for _ in range(2)
        ]
        assert listener_sockets == [mocker.sentinel.listener_socket, mocker.sentinel.listener_socket]

    @pytest.mark.parametrize(
        ["use_ssl", "use_asyncio_transport"],
        [
            pytest.param(False, False, id="NO_SSL-use_asyncio_transport==False"),
            pytest.param(False, True, id="NO_SSL-use_asyncio_transport==True"),
            pytest.param(True, True, id="USE_SSL"),
        ],
        indirect=["use_asyncio_transport"],
    )
    async def test____create_tcp_listeners____error_getaddrinfo_returns_empty_list(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncioBackend,
        use_ssl: bool,
        mock_ssl_context: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from socket import AF_UNSPEC, AI_PASSIVE, SOCK_STREAM

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
            "easynetwork_asyncio.backend.open_listener_sockets_from_getaddrinfo_result",
            side_effect=AssertionError,
        )
        mock_ListenerSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.backend.ListenerSocketAdapter",
            side_effect=AssertionError,
        )

        # Act
        with pytest.raises(OSError, match=r"getaddrinfo\('remote_address'\) returned empty list"):
            if use_ssl:
                await backend.create_ssl_over_tcp_listeners(
                    remote_host,
                    remote_port,
                    mocker.sentinel.backlog,
                    ssl_context=mock_ssl_context,
                    ssl_handshake_timeout=123456.789,
                    ssl_shutdown_timeout=9876543.21,
                    reuse_port=mocker.sentinel.reuse_port,
                )
            else:
                await backend.create_tcp_listeners(
                    remote_host,
                    remote_port,
                    mocker.sentinel.backlog,
                    reuse_port=mocker.sentinel.reuse_port,
                )

        # Assert
        mock_getaddrinfo.assert_awaited_once_with(
            remote_host,
            remote_port,
            family=AF_UNSPEC,
            type=SOCK_STREAM,
            proto=0,
            flags=AI_PASSIVE,
        )
        mock_open_listeners.assert_not_called()
        mock_ListenerSocketAdapter.assert_not_called()

    @pytest.mark.parametrize("use_asyncio_transport", [False], indirect=True)
    async def test____create_ssl_over_tcp_listeners____ssl_not_supported(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncioBackend,
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
            "easynetwork_asyncio.backend.open_listener_sockets_from_getaddrinfo_result",
            side_effect=AssertionError,
        )
        mock_ListenerSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.backend.ListenerSocketAdapter",
            side_effect=AssertionError,
        )

        # Act
        with pytest.raises(ValueError, match=r"^SSL\/TLS not supported with transport=False$"):
            await backend.create_ssl_over_tcp_listeners(
                remote_host,
                remote_port,
                mocker.sentinel.backlog,
                ssl_context=mock_ssl_context,
                ssl_handshake_timeout=123456.789,
                ssl_shutdown_timeout=9876543.21,
                reuse_port=mocker.sentinel.reuse_port,
            )

        # Assert
        mock_getaddrinfo.assert_not_called()
        mock_open_listeners.assert_not_called()
        mock_ListenerSocketAdapter.assert_not_called()

    @pytest.mark.parametrize("remote_address", [("remote_address", 5000), None], indirect=True)
    async def test____create_udp_endpoint____use_loop_create_datagram_endpoint(
        self,
        event_loop: asyncio.AbstractEventLoop,
        local_address: tuple[str, int] | None,
        remote_address: tuple[str, int] | None,
        backend: AsyncioBackend,
        mock_datagram_endpoint_factory: Callable[[], MagicMock],
        use_asyncio_transport: bool,
        mock_udp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        mock_endpoint = mock_datagram_endpoint_factory()
        mock_AsyncioTransportDatagramSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.backend.AsyncioTransportDatagramSocketAdapter",
            return_value=mocker.sentinel.socket,
        )
        mock_RawDatagramSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.backend.RawDatagramSocketAdapter",
            return_value=mocker.sentinel.socket,
        )
        mock_create_datagram_endpoint: AsyncMock = mocker.patch(
            "easynetwork_asyncio.backend.create_datagram_endpoint",
            new_callable=mocker.AsyncMock,
            return_value=mock_endpoint,
        )
        mock_create_datagram_socket: AsyncMock = mocker.patch(
            "easynetwork_asyncio.backend.create_datagram_socket",
            new_callable=mocker.AsyncMock,
            return_value=mock_udp_socket,
        )

        # Act
        socket = await backend.create_udp_endpoint(
            local_address=local_address,
            remote_address=remote_address,
            reuse_port=True,
        )

        # Assert
        mock_create_datagram_socket.assert_awaited_once_with(
            loop=event_loop,
            local_address=local_address,
            remote_address=remote_address,
            reuse_port=True,
        )
        if use_asyncio_transport:
            mock_create_datagram_endpoint.assert_awaited_once_with(socket=mock_udp_socket)
            mock_AsyncioTransportDatagramSocketAdapter.assert_called_once_with(mock_endpoint)
            mock_RawDatagramSocketAdapter.assert_not_called()
        else:
            mock_create_datagram_endpoint.assert_not_awaited()
            mock_RawDatagramSocketAdapter.assert_called_once_with(mock_udp_socket, event_loop)
            mock_AsyncioTransportDatagramSocketAdapter.assert_not_called()

        assert socket is mocker.sentinel.socket
        mock_udp_socket.setblocking.assert_called_with(False)

    async def test____wrap_udp_socket____use_loop_create_datagram_endpoint(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncioBackend,
        use_asyncio_transport: bool,
        mock_udp_socket: MagicMock,
        mock_datagram_endpoint_factory: Callable[[], MagicMock],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_endpoint = mock_datagram_endpoint_factory()
        mock_AsyncioTransportDatagramSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.backend.AsyncioTransportDatagramSocketAdapter",
            return_value=mocker.sentinel.socket,
        )
        mock_RawDatagramSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.backend.RawDatagramSocketAdapter",
            return_value=mocker.sentinel.socket,
        )
        mock_create_datagram_endpoint: AsyncMock = mocker.patch(
            "easynetwork_asyncio.backend.create_datagram_endpoint",
            new_callable=mocker.AsyncMock,
            return_value=mock_endpoint,
        )

        # Act
        socket = await backend.wrap_udp_socket(mock_udp_socket)

        # Assert
        if use_asyncio_transport:
            mock_create_datagram_endpoint.assert_awaited_once_with(socket=mock_udp_socket)
            mock_AsyncioTransportDatagramSocketAdapter.assert_called_once_with(mock_endpoint)
            mock_RawDatagramSocketAdapter.assert_not_called()
        else:
            mock_create_datagram_endpoint.assert_not_awaited()
            mock_RawDatagramSocketAdapter.assert_called_once_with(mock_udp_socket, event_loop)
            mock_AsyncioTransportDatagramSocketAdapter.assert_not_called()

        assert socket is mocker.sentinel.socket
        mock_udp_socket.setblocking.assert_called_with(False)

    async def test____create_lock____use_asyncio_Lock_class(
        self,
        backend: AsyncioBackend,
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
        backend: AsyncioBackend,
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
        backend: AsyncioBackend,
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
        backend: AsyncioBackend,
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
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncioBackend,
    ) -> None:
        # Arrange
        from easynetwork_asyncio.threads import ThreadsPortal

        # Act
        threads_portal = backend.create_threads_portal()

        # Assert
        assert isinstance(threads_portal, ThreadsPortal)
        assert threads_portal.loop is event_loop
