from __future__ import annotations

import contextlib
import errno
import os
from socket import AF_INET6, IPPROTO_TCP, SO_ERROR, SO_KEEPALIVE, SOL_SOCKET, TCP_NODELAY
from typing import TYPE_CHECKING, Any

from easynetwork.api_async.client.tcp import AsyncTCPNetworkClient
from easynetwork.exceptions import ClientClosedError, IncrementalDeserializeError, StreamProtocolParseError
from easynetwork.lowlevel._stream import StreamDataConsumer
from easynetwork.lowlevel.constants import (
    CLOSED_SOCKET_ERRNOS,
    DEFAULT_STREAM_BUFSIZE,
    SSL_HANDSHAKE_TIMEOUT,
    SSL_SHUTDOWN_TIMEOUT,
)
from easynetwork.lowlevel.socket import IPv4SocketAddress, IPv6SocketAddress, SocketProxy, _get_socket_extra
from easynetwork.lowlevel.typed_attr import TypedAttributeProvider

import pytest
import pytest_asyncio

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture

from ...._utils import AsyncDummyLock
from ....base import UNSUPPORTED_FAMILIES
from .base import BaseTestClient


@pytest.mark.asyncio
class TestAsyncTCPNetworkClient(BaseTestClient):
    @pytest.fixture(scope="class", params=["AF_INET", "AF_INET6"])
    @staticmethod
    def socket_family(request: Any) -> Any:
        import socket

        return getattr(socket, request.param)

    @pytest.fixture(scope="class")
    @staticmethod
    def global_local_address() -> tuple[str, int]:
        return ("local_address", 12345)

    @pytest.fixture(scope="class")
    @staticmethod
    def global_remote_address() -> tuple[str, int]:
        return ("remote_address", 5000)

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_ssl_create_default_context(mock_ssl_context: MagicMock, mocker: MockerFixture) -> MagicMock:
        return mocker.patch("ssl.create_default_context", autospec=True, return_value=mock_ssl_context)

    @pytest.fixture
    @staticmethod
    def mock_stream_data_consumer(mocker: MockerFixture) -> MagicMock:
        return mocker.NonCallableMagicMock(spec=StreamDataConsumer)

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_stream_data_consumer_cls(mocker: MockerFixture, mock_stream_data_consumer: MagicMock) -> MagicMock:
        return mocker.patch("easynetwork.lowlevel._stream.StreamDataConsumer", return_value=mock_stream_data_consumer)

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_new_backend(mocker: MockerFixture, mock_backend: MagicMock) -> MagicMock:
        from easynetwork.lowlevel.api_async.backend.factory import AsyncBackendFactory

        return mocker.patch.object(AsyncBackendFactory, "new", return_value=mock_backend)

    @pytest.fixture(autouse=True)
    @classmethod
    def local_address(
        cls,
        mock_tcp_socket: MagicMock,
        socket_family: int,
        global_local_address: tuple[str, int],
    ) -> tuple[str, int]:
        cls.set_local_address_to_socket_mock(
            mock_tcp_socket,
            socket_family,
            global_local_address,
        )
        return global_local_address

    @pytest.fixture(autouse=True)
    @classmethod
    def remote_address(
        cls,
        mock_tcp_socket: MagicMock,
        socket_family: int,
        global_remote_address: tuple[str, int],
    ) -> tuple[str, int]:
        cls.set_remote_address_to_socket_mock(
            mock_tcp_socket,
            socket_family,
            global_remote_address,
        )
        return global_remote_address

    @pytest.fixture(autouse=True)
    @staticmethod
    def set_default_socket_mock_configuration(
        mock_tcp_socket: MagicMock,
        mock_backend: MagicMock,
        socket_family: int,
        mock_stream_socket_adapter: MagicMock,
    ) -> None:
        mock_tcp_socket.family = socket_family
        mock_tcp_socket.getsockopt.return_value = 0  # Needed for tests dealing with send_packet()
        del mock_tcp_socket.sendall
        del mock_tcp_socket.recv

        mock_backend.create_tcp_connection.return_value = mock_stream_socket_adapter
        mock_backend.create_ssl_over_tcp_connection.return_value = mock_stream_socket_adapter
        mock_backend.wrap_stream_socket.return_value = mock_stream_socket_adapter
        mock_backend.wrap_ssl_over_stream_socket_client_side.return_value = mock_stream_socket_adapter

        mock_stream_socket_adapter.extra_attributes = _get_socket_extra(mock_tcp_socket, wrap_in_proxy=False)
        mock_stream_socket_adapter.extra.side_effect = TypedAttributeProvider.extra.__get__(mock_stream_socket_adapter)

    @pytest.fixture  # DO NOT set autouse=True
    @staticmethod
    def setup_producer_mock(mock_stream_protocol: MagicMock) -> None:
        mock_stream_protocol.generate_chunks.side_effect = lambda packet: iter(
            [str(packet).encode("ascii").removeprefix(b"sentinel.") + b"\n"]
        )

    @pytest.fixture  # DO NOT set autouse=True
    @staticmethod
    def setup_consumer_mock(mock_stream_data_consumer: MagicMock, mocker: MockerFixture) -> None:
        bytes_buffer: bytes = b""

        sentinel = mocker.sentinel

        def feed_side_effect(chunk: bytes) -> None:
            nonlocal bytes_buffer
            bytes_buffer += chunk

        def next_side_effect() -> Any:
            nonlocal bytes_buffer
            data, separator, bytes_buffer = bytes_buffer.partition(b"\n")
            if not separator:
                assert not bytes_buffer
                bytes_buffer = data
                raise StopIteration
            return getattr(sentinel, data.decode("ascii"))

        mock_stream_data_consumer.feed.side_effect = feed_side_effect
        mock_stream_data_consumer.__iter__.side_effect = lambda: mock_stream_data_consumer
        mock_stream_data_consumer.__next__.side_effect = next_side_effect

    @pytest.fixture
    @staticmethod
    def client_not_connected(
        remote_address: tuple[str, int],
        mock_backend: MagicMock,
        mock_stream_protocol: MagicMock,
    ) -> AsyncTCPNetworkClient[Any, Any]:
        client: AsyncTCPNetworkClient[Any, Any] = AsyncTCPNetworkClient(
            remote_address,
            mock_stream_protocol,
            backend=mock_backend,
        )
        assert not client.is_connected()
        return client

    @pytest_asyncio.fixture
    @staticmethod
    async def client_connected(client_not_connected: AsyncTCPNetworkClient[Any, Any]) -> AsyncTCPNetworkClient[Any, Any]:
        await client_not_connected.wait_connected()
        assert client_not_connected.is_connected()
        return client_not_connected

    @pytest.fixture(params=[False, True], ids=lambda boolean: f"client_connected=={boolean}")
    @staticmethod
    def client_connected_or_not(request: pytest.FixtureRequest) -> AsyncTCPNetworkClient[Any, Any]:
        client_to_use: str = {False: "client_not_connected", True: "client_connected"}[getattr(request, "param")]
        return request.getfixturevalue(client_to_use)

    async def test____dunder_init____connect_to_remote(
        self,
        remote_address: tuple[str, int],
        mock_tcp_socket: MagicMock,
        mock_backend: MagicMock,
        mock_stream_data_consumer_cls: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_new_backend: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_backend.create_ssl_over_tcp_connection.side_effect = AssertionError

        # Act
        client: AsyncTCPNetworkClient[Any, Any] = AsyncTCPNetworkClient(
            remote_address,
            protocol=mock_stream_protocol,
            local_address=mocker.sentinel.local_address,
            happy_eyeballs_delay=mocker.sentinel.happy_eyeballs_delay,
        )
        await client.wait_connected()

        # Assert
        mock_new_backend.assert_called_once_with(None)
        mock_stream_data_consumer_cls.assert_called_once_with(mock_stream_protocol)
        mock_backend.create_tcp_connection.assert_awaited_once_with(
            *remote_address,
            local_address=mocker.sentinel.local_address,
            happy_eyeballs_delay=mocker.sentinel.happy_eyeballs_delay,
        )
        assert mock_tcp_socket.mock_calls == [
            mocker.call.setsockopt(IPPROTO_TCP, TCP_NODELAY, True),
            mocker.call.setsockopt(SOL_SOCKET, SO_KEEPALIVE, True),
        ]
        assert isinstance(client.socket, SocketProxy)

    async def test____dunder_init____backend____from_string(
        self,
        remote_address: tuple[str, int],
        mock_stream_protocol: MagicMock,
        mock_new_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act
        _ = AsyncTCPNetworkClient(
            remote_address,
            protocol=mock_stream_protocol,
            backend="custom_backend",
            backend_kwargs={"arg1": 1, "arg2": "2"},
        )

        # Assert
        mock_new_backend.assert_called_once_with("custom_backend", arg1=1, arg2="2")

    async def test____dunder_init____backend____explicit_argument(
        self,
        remote_address: tuple[str, int],
        mock_stream_protocol: MagicMock,
        mock_backend: MagicMock,
        mock_new_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act
        _ = AsyncTCPNetworkClient(
            remote_address,
            protocol=mock_stream_protocol,
            backend=mock_backend,
        )

        # Assert
        mock_new_backend.assert_not_called()

    async def test____dunder_init____use_given_socket(
        self,
        mock_tcp_socket: MagicMock,
        mock_backend: MagicMock,
        mock_stream_data_consumer_cls: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_new_backend: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        client: AsyncTCPNetworkClient[Any, Any] = AsyncTCPNetworkClient(mock_tcp_socket, protocol=mock_stream_protocol)
        await client.wait_connected()

        # Assert
        mock_new_backend.assert_called_once_with(None)
        mock_stream_data_consumer_cls.assert_called_once_with(mock_stream_protocol)
        mock_backend.wrap_stream_socket.assert_awaited_once_with(mock_tcp_socket)
        assert mock_tcp_socket.mock_calls == [
            mocker.call.getpeername(),
            mocker.call.setsockopt(IPPROTO_TCP, TCP_NODELAY, True),
            mocker.call.setsockopt(SOL_SOCKET, SO_KEEPALIVE, True),
        ]
        assert isinstance(client.socket, SocketProxy)

    async def test____dunder_init____use_given_socket____error_no_remote_address(
        self,
        mock_tcp_socket: MagicMock,
        mock_stream_protocol: MagicMock,
    ) -> None:
        # Arrange
        self.configure_socket_mock_to_raise_ENOTCONN(mock_tcp_socket)

        # Act
        with pytest.raises(OSError) as exc_info:
            _ = AsyncTCPNetworkClient(mock_tcp_socket, protocol=mock_stream_protocol)

        # Assert
        assert exc_info.value.errno == errno.ENOTCONN

    @pytest.mark.parametrize("socket_family", list(UNSUPPORTED_FAMILIES), indirect=True)
    @pytest.mark.parametrize("use_ssl", [False, True], ids=lambda p: f"use_ssl=={p}")
    async def test____dunder_init____use_given_socket____invalid_socket_family(
        self,
        use_ssl: bool,
        mock_tcp_socket: MagicMock,
        mock_stream_protocol: MagicMock,
    ) -> None:
        # Arrange
        ssl_context: bool = False
        server_hostname: str | None = None
        if use_ssl:
            ssl_context = True
            server_hostname = "test.example.com"

        # Act & Assert
        with pytest.raises(ValueError, match=r"^Only these families are supported: .+$"):
            _ = AsyncTCPNetworkClient(
                mock_tcp_socket,
                protocol=mock_stream_protocol,
                ssl=ssl_context,
                server_hostname=server_hostname,
            )

    @pytest.mark.parametrize("use_socket", [False, True], ids=lambda p: f"use_socket=={p}")
    async def test____dunder_init____protocol____invalid_value(
        self,
        request: pytest.FixtureRequest,
        use_socket: bool,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a StreamProtocol object, got .*$"):
            if use_socket:
                _ = AsyncTCPNetworkClient(
                    request.getfixturevalue("mock_tcp_socket"),
                    mock_datagram_protocol,
                )
            else:
                _ = AsyncTCPNetworkClient(
                    request.getfixturevalue("remote_address"),
                    mock_datagram_protocol,
                )

    @pytest.mark.parametrize("max_recv_size", [None, 1, 2**64], ids=lambda p: f"max_recv_size=={p}")
    @pytest.mark.parametrize("use_socket", [False, True], ids=lambda p: f"use_socket=={p}")
    async def test____dunder_init____max_recv_size____valid_value(
        self,
        request: pytest.FixtureRequest,
        max_recv_size: int | None,
        use_socket: bool,
        mock_stream_protocol: MagicMock,
    ) -> None:
        # Arrange
        expected_size: int = max_recv_size if max_recv_size is not None else DEFAULT_STREAM_BUFSIZE

        # Act
        client: AsyncTCPNetworkClient[Any, Any]
        if use_socket:
            client = AsyncTCPNetworkClient(
                request.getfixturevalue("mock_tcp_socket"),
                mock_stream_protocol,
                max_recv_size=max_recv_size,
            )
        else:
            client = AsyncTCPNetworkClient(
                request.getfixturevalue("remote_address"),
                protocol=mock_stream_protocol,
                max_recv_size=max_recv_size,
            )

        # Assert
        assert client.max_recv_size == expected_size

    @pytest.mark.parametrize("max_recv_size", [0, -1, 10.4], ids=lambda p: f"max_recv_size=={p}")
    @pytest.mark.parametrize("use_socket", [False, True], ids=lambda p: f"use_socket=={p}")
    async def test____dunder_init____max_recv_size____invalid_value(
        self,
        request: pytest.FixtureRequest,
        max_recv_size: Any,
        use_socket: bool,
        mock_stream_protocol: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^'max_recv_size' must be a strictly positive integer$"):
            if use_socket:
                _ = AsyncTCPNetworkClient(
                    request.getfixturevalue("mock_tcp_socket"),
                    mock_stream_protocol,
                    max_recv_size=max_recv_size,
                )
            else:
                _ = AsyncTCPNetworkClient(
                    request.getfixturevalue("remote_address"),
                    protocol=mock_stream_protocol,
                    max_recv_size=max_recv_size,
                )

    @pytest.mark.parametrize("use_socket", [False, True], ids=lambda p: f"use_socket=={p}")
    async def test____dunder_init____ssl(
        self,
        use_socket: bool,
        remote_address: tuple[str, int],
        mock_tcp_socket: MagicMock,
        mock_backend: MagicMock,
        mock_stream_data_consumer_cls: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_new_backend: MagicMock,
        mock_ssl_context: MagicMock,
        mock_ssl_create_default_context: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_backend.create_tcp_connection.side_effect = AssertionError
        mock_backend.wrap_stream_socket.side_effect = AssertionError

        # Act
        client: AsyncTCPNetworkClient[Any, Any]
        if use_socket:
            client = AsyncTCPNetworkClient(
                mock_tcp_socket,
                protocol=mock_stream_protocol,
                ssl=mock_ssl_context,
                server_hostname="server_hostname",
                ssl_handshake_timeout=mocker.sentinel.ssl_handshake_timeout,
                ssl_shutdown_timeout=mocker.sentinel.ssl_shutdown_timeout,
            )
        else:
            client = AsyncTCPNetworkClient(
                remote_address,
                protocol=mock_stream_protocol,
                ssl=mock_ssl_context,
                server_hostname="server_hostname",
                ssl_handshake_timeout=mocker.sentinel.ssl_handshake_timeout,
                ssl_shutdown_timeout=mocker.sentinel.ssl_shutdown_timeout,
                local_address=mocker.sentinel.local_address,
                happy_eyeballs_delay=mocker.sentinel.happy_eyeballs_delay,
            )
        await client.wait_connected()

        # Assert
        mock_new_backend.assert_called_once_with(None)
        mock_stream_data_consumer_cls.assert_called_once_with(mock_stream_protocol)
        mock_ssl_create_default_context.assert_not_called()
        if use_socket:
            mock_backend.wrap_ssl_over_stream_socket_client_side.assert_awaited_once_with(
                mock_tcp_socket,
                ssl_context=mock_ssl_context,
                server_hostname="server_hostname",
                ssl_handshake_timeout=mocker.sentinel.ssl_handshake_timeout,
                ssl_shutdown_timeout=mocker.sentinel.ssl_shutdown_timeout,
            )
            assert mock_tcp_socket.mock_calls == [
                mocker.call.getpeername(),
                mocker.call.setsockopt(IPPROTO_TCP, TCP_NODELAY, True),
                mocker.call.setsockopt(SOL_SOCKET, SO_KEEPALIVE, True),
            ]
        else:
            mock_backend.create_ssl_over_tcp_connection.assert_awaited_once_with(
                *remote_address,
                ssl_context=mock_ssl_context,
                server_hostname="server_hostname",
                ssl_handshake_timeout=mocker.sentinel.ssl_handshake_timeout,
                ssl_shutdown_timeout=mocker.sentinel.ssl_shutdown_timeout,
                local_address=mocker.sentinel.local_address,
                happy_eyeballs_delay=mocker.sentinel.happy_eyeballs_delay,
            )
            assert mock_tcp_socket.mock_calls == [
                mocker.call.setsockopt(IPPROTO_TCP, TCP_NODELAY, True),
                mocker.call.setsockopt(SOL_SOCKET, SO_KEEPALIVE, True),
            ]
        assert isinstance(client.socket, SocketProxy)

    @pytest.mark.parametrize("use_socket", [False, True], ids=lambda p: f"use_socket=={p}")
    @pytest.mark.parametrize(
        "ssl_parameter",
        [
            "server_hostname",
            "ssl_handshake_timeout",
            "ssl_shutdown_timeout",
            "ssl_shared_lock",
        ],
    )
    async def test____dunder_init____ssl____useless_parameter_if_no_context(
        self,
        ssl_parameter: str,
        use_socket: bool,
        remote_address: tuple[str, int],
        mock_tcp_socket: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        kwargs = {ssl_parameter: mocker.sentinel.value}

        # Act & Assert
        with pytest.raises(ValueError, match=rf"^{ssl_parameter} is only meaningful with ssl$"):
            if use_socket:
                _ = AsyncTCPNetworkClient(
                    mock_tcp_socket,
                    protocol=mock_stream_protocol,
                    ssl=None,
                    **kwargs,
                )
            else:
                _ = AsyncTCPNetworkClient(
                    remote_address,
                    protocol=mock_stream_protocol,
                    ssl=None,
                    **kwargs,
                )

    @pytest.mark.parametrize("use_socket", [False, True], ids=lambda p: f"use_socket=={p}")
    async def test____dunder_init____ssl____default_timeouts(
        self,
        use_socket: bool,
        remote_address: tuple[str, int],
        mock_tcp_socket: MagicMock,
        mock_backend: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_ssl_context: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_backend.create_tcp_connection.side_effect = AssertionError
        mock_backend.wrap_stream_socket.side_effect = AssertionError

        # Act
        client: AsyncTCPNetworkClient[Any, Any]
        if use_socket:
            client = AsyncTCPNetworkClient(
                mock_tcp_socket,
                protocol=mock_stream_protocol,
                ssl=mock_ssl_context,
                server_hostname="server_hostname",
                ssl_handshake_timeout=None,
                ssl_shutdown_timeout=None,
            )
        else:
            client = AsyncTCPNetworkClient(
                remote_address,
                protocol=mock_stream_protocol,
                ssl=mock_ssl_context,
                server_hostname="server_hostname",
                ssl_handshake_timeout=None,
                ssl_shutdown_timeout=None,
                local_address=mocker.sentinel.local_address,
                happy_eyeballs_delay=mocker.sentinel.happy_eyeballs_delay,
            )
        await client.wait_connected()

        # Assert
        if use_socket:
            mock_backend.wrap_ssl_over_stream_socket_client_side.assert_awaited_once_with(
                mock_tcp_socket,
                ssl_context=mock_ssl_context,
                server_hostname="server_hostname",
                ssl_handshake_timeout=SSL_HANDSHAKE_TIMEOUT,
                ssl_shutdown_timeout=SSL_SHUTDOWN_TIMEOUT,
            )
        else:
            mock_backend.create_ssl_over_tcp_connection.assert_awaited_once_with(
                *remote_address,
                ssl_context=mock_ssl_context,
                server_hostname="server_hostname",
                ssl_handshake_timeout=SSL_HANDSHAKE_TIMEOUT,
                ssl_shutdown_timeout=SSL_SHUTDOWN_TIMEOUT,
                local_address=mocker.sentinel.local_address,
                happy_eyeballs_delay=mocker.sentinel.happy_eyeballs_delay,
            )

    @pytest.mark.parametrize("use_socket", [False, True], ids=lambda p: f"use_socket=={p}")
    async def test____dunder_init____ssl____server_hostname____do_not_disable_hostname_check_for_external_context(
        self,
        use_socket: bool,
        remote_address: tuple[str, int],
        mock_tcp_socket: MagicMock,
        mock_backend: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_ssl_context: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        check_hostname_by_default: bool = mock_ssl_context.check_hostname
        assert check_hostname_by_default

        mock_backend.create_tcp_connection.side_effect = AssertionError
        mock_backend.wrap_stream_socket.side_effect = AssertionError

        # Act
        client: AsyncTCPNetworkClient[Any, Any]
        if use_socket:
            client = AsyncTCPNetworkClient(
                mock_tcp_socket,
                protocol=mock_stream_protocol,
                ssl=mock_ssl_context,
                server_hostname="",
                ssl_handshake_timeout=mocker.sentinel.ssl_handshake_timeout,
                ssl_shutdown_timeout=mocker.sentinel.ssl_shutdown_timeout,
            )
        else:
            client = AsyncTCPNetworkClient(
                remote_address,
                protocol=mock_stream_protocol,
                ssl=mock_ssl_context,
                server_hostname="",
                ssl_handshake_timeout=mocker.sentinel.ssl_handshake_timeout,
                ssl_shutdown_timeout=mocker.sentinel.ssl_shutdown_timeout,
                local_address=mocker.sentinel.local_address,
                happy_eyeballs_delay=mocker.sentinel.happy_eyeballs_delay,
            )
        await client.wait_connected()

        # Assert
        if use_socket:
            mock_backend.wrap_ssl_over_stream_socket_client_side.assert_awaited_once_with(
                mock_tcp_socket,
                ssl_context=mock_ssl_context,
                server_hostname="",
                ssl_handshake_timeout=mocker.sentinel.ssl_handshake_timeout,
                ssl_shutdown_timeout=mocker.sentinel.ssl_shutdown_timeout,
            )
        else:
            mock_backend.create_ssl_over_tcp_connection.assert_awaited_once_with(
                *remote_address,
                ssl_context=mock_ssl_context,
                server_hostname="",
                ssl_handshake_timeout=mocker.sentinel.ssl_handshake_timeout,
                ssl_shutdown_timeout=mocker.sentinel.ssl_shutdown_timeout,
                local_address=mocker.sentinel.local_address,
                happy_eyeballs_delay=mocker.sentinel.happy_eyeballs_delay,
            )
        assert mock_ssl_context.check_hostname is True

    async def test____dunder_init____ssl____server_hostname____required_if_socket_is_given(
        self,
        mock_tcp_socket: MagicMock,
        mock_backend: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_ssl_context: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_backend.create_tcp_connection.side_effect = AssertionError
        mock_backend.wrap_stream_socket.side_effect = AssertionError

        # Act & Assert
        with pytest.raises(ValueError, match=r"^You must set server_hostname when using ssl without a host$"):
            _ = AsyncTCPNetworkClient(
                mock_tcp_socket,
                protocol=mock_stream_protocol,
                ssl=mock_ssl_context,
                server_hostname=None,
                ssl_handshake_timeout=mocker.sentinel.ssl_handshake_timeout,
                ssl_shutdown_timeout=mocker.sentinel.ssl_shutdown_timeout,
            )

    @pytest.mark.parametrize("use_socket", [False, True], ids=lambda p: f"use_socket=={p}")
    async def test____dunder_init____ssl____create_default_context(
        self,
        use_socket: bool,
        remote_address: tuple[str, int],
        mock_tcp_socket: MagicMock,
        mock_backend: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_ssl_context: MagicMock,
        mock_ssl_create_default_context: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_backend.create_tcp_connection.side_effect = AssertionError
        mock_backend.wrap_stream_socket.side_effect = AssertionError

        # Act
        client: AsyncTCPNetworkClient[Any, Any]
        if use_socket:
            client = AsyncTCPNetworkClient(
                mock_tcp_socket,
                protocol=mock_stream_protocol,
                ssl=True,
                server_hostname="server_hostname",
                ssl_handshake_timeout=mocker.sentinel.ssl_handshake_timeout,
                ssl_shutdown_timeout=mocker.sentinel.ssl_shutdown_timeout,
            )
        else:
            client = AsyncTCPNetworkClient(
                remote_address,
                protocol=mock_stream_protocol,
                ssl=True,
                server_hostname="server_hostname",
                ssl_handshake_timeout=mocker.sentinel.ssl_handshake_timeout,
                ssl_shutdown_timeout=mocker.sentinel.ssl_shutdown_timeout,
                local_address=mocker.sentinel.local_address,
                happy_eyeballs_delay=mocker.sentinel.happy_eyeballs_delay,
            )
        await client.wait_connected()

        # Assert
        mock_ssl_create_default_context.assert_called_once_with()
        if use_socket:
            mock_backend.wrap_ssl_over_stream_socket_client_side.assert_awaited_once_with(
                mock_tcp_socket,
                ssl_context=mock_ssl_context,
                server_hostname="server_hostname",
                ssl_handshake_timeout=mocker.sentinel.ssl_handshake_timeout,
                ssl_shutdown_timeout=mocker.sentinel.ssl_shutdown_timeout,
            )
        else:
            mock_backend.create_ssl_over_tcp_connection.assert_awaited_once_with(
                *remote_address,
                ssl_context=mock_ssl_context,
                server_hostname="server_hostname",
                ssl_handshake_timeout=mocker.sentinel.ssl_handshake_timeout,
                ssl_shutdown_timeout=mocker.sentinel.ssl_shutdown_timeout,
                local_address=mocker.sentinel.local_address,
                happy_eyeballs_delay=mocker.sentinel.happy_eyeballs_delay,
            )

    @pytest.mark.parametrize("use_socket", [False, True], ids=lambda p: f"use_socket=={p}")
    async def test____dunder_init____ssl____create_default_context____disable_hostname_check(
        self,
        use_socket: bool,
        remote_address: tuple[str, int],
        mock_tcp_socket: MagicMock,
        mock_backend: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_ssl_context: MagicMock,
        mock_ssl_create_default_context: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        check_hostname_by_default: bool = mock_ssl_context.check_hostname
        assert check_hostname_by_default

        mock_backend.create_tcp_connection.side_effect = AssertionError
        mock_backend.wrap_stream_socket.side_effect = AssertionError

        # Act
        client: AsyncTCPNetworkClient[Any, Any]
        if use_socket:
            client = AsyncTCPNetworkClient(
                mock_tcp_socket,
                protocol=mock_stream_protocol,
                ssl=True,
                server_hostname="",
                ssl_handshake_timeout=mocker.sentinel.ssl_handshake_timeout,
                ssl_shutdown_timeout=mocker.sentinel.ssl_shutdown_timeout,
            )
        else:
            client = AsyncTCPNetworkClient(
                remote_address,
                protocol=mock_stream_protocol,
                ssl=True,
                server_hostname="",
                ssl_handshake_timeout=mocker.sentinel.ssl_handshake_timeout,
                ssl_shutdown_timeout=mocker.sentinel.ssl_shutdown_timeout,
                local_address=mocker.sentinel.local_address,
                happy_eyeballs_delay=mocker.sentinel.happy_eyeballs_delay,
            )
        await client.wait_connected()

        # Assert
        mock_ssl_create_default_context.assert_called_once_with()
        if use_socket:
            mock_backend.wrap_ssl_over_stream_socket_client_side.assert_awaited_once_with(
                mock_tcp_socket,
                ssl_context=mock_ssl_context,
                server_hostname="",
                ssl_handshake_timeout=mocker.sentinel.ssl_handshake_timeout,
                ssl_shutdown_timeout=mocker.sentinel.ssl_shutdown_timeout,
            )
        else:
            mock_backend.create_ssl_over_tcp_connection.assert_awaited_once_with(
                *remote_address,
                ssl_context=mock_ssl_context,
                server_hostname="",
                ssl_handshake_timeout=mocker.sentinel.ssl_handshake_timeout,
                ssl_shutdown_timeout=mocker.sentinel.ssl_shutdown_timeout,
                local_address=mocker.sentinel.local_address,
                happy_eyeballs_delay=mocker.sentinel.happy_eyeballs_delay,
            )
        assert mock_ssl_context.check_hostname is False

    async def test____is_closing____connection_not_performed_yet(
        self,
        client_not_connected: AsyncTCPNetworkClient[Any, Any],
    ) -> None:
        # Arrange

        # Act & Assert
        assert not client_not_connected.is_closing()
        await client_not_connected.wait_connected()
        assert not client_not_connected.is_closing()

    async def test____aclose____await_socket_close(
        self,
        client_connected: AsyncTCPNetworkClient[Any, Any],
        mock_stream_socket_adapter: MagicMock,
    ) -> None:
        # Arrange
        assert not client_connected.is_closing()

        # Act
        await client_connected.aclose()

        # Assert
        assert client_connected.is_closing()
        mock_stream_socket_adapter.aclose.assert_awaited_once_with()

    async def test____aclose____connection_not_performed_yet(
        self,
        client_not_connected: AsyncTCPNetworkClient[Any, Any],
        mock_stream_socket_adapter: MagicMock,
    ) -> None:
        # Arrange
        assert not client_not_connected.is_closing()

        # Act
        await client_not_connected.aclose()

        # Assert
        assert client_not_connected.is_closing()
        mock_stream_socket_adapter.aclose.assert_not_awaited()

    async def test____aclose____already_closed(
        self,
        client_connected: AsyncTCPNetworkClient[Any, Any],
        mock_stream_socket_adapter: MagicMock,
    ) -> None:
        # Arrange
        await client_connected.aclose()
        assert client_connected.is_closing()

        # Act
        await client_connected.aclose()

        # Assert
        assert mock_stream_socket_adapter.aclose.await_count == 2

    async def test____aclose____cancelled(
        self,
        client_connected: AsyncTCPNetworkClient[Any, Any],
        mock_stream_socket_adapter: MagicMock,
        fake_cancellation_cls: type[BaseException],
    ) -> None:
        # Arrange
        mock_stream_socket_adapter.aclose.side_effect = fake_cancellation_cls

        # Act
        with pytest.raises(fake_cancellation_cls):
            await client_connected.aclose()

        # Assert
        mock_stream_socket_adapter.aclose.assert_awaited_once_with()

    async def test____get_local_address____return_saved_address(
        self,
        client_connected: AsyncTCPNetworkClient[Any, Any],
        socket_family: int,
        local_address: tuple[str, int],
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_tcp_socket.getsockname.reset_mock()

        # Act
        address = client_connected.get_local_address()

        # Assert
        if socket_family == AF_INET6:
            assert isinstance(address, IPv6SocketAddress)
        else:
            assert isinstance(address, IPv4SocketAddress)
        mock_tcp_socket.getsockname.assert_called_once()
        assert address.host == local_address[0]
        assert address.port == local_address[1]

    async def test____get_local_address____error_connection_not_performed(
        self,
        client_not_connected: AsyncTCPNetworkClient[Any, Any],
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act
        with pytest.raises(OSError):
            client_not_connected.get_local_address()

        # Assert
        mock_tcp_socket.getsockname.assert_not_called()

    async def test____get_local_address____client_closed(
        self,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange
        await client_connected_or_not.aclose()
        assert client_connected_or_not.is_closing()

        # Act
        with pytest.raises(ClientClosedError):
            client_connected_or_not.get_local_address()

        # Assert
        mock_tcp_socket.getsockname.assert_not_called()

    async def test____get_remote_address____return_saved_address(
        self,
        client_connected: AsyncTCPNetworkClient[Any, Any],
        remote_address: tuple[str, int],
        socket_family: int,
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_tcp_socket.getpeername.reset_mock()

        # Act
        address = client_connected.get_remote_address()

        # Assert
        if socket_family == AF_INET6:
            assert isinstance(address, IPv6SocketAddress)
        else:
            assert isinstance(address, IPv4SocketAddress)
        mock_tcp_socket.getpeername.assert_called_once()
        assert address.host == remote_address[0]
        assert address.port == remote_address[1]

    async def test____get_remote_address____error_connection_not_performed(
        self,
        client_not_connected: AsyncTCPNetworkClient[Any, Any],
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act
        with pytest.raises(OSError):
            client_not_connected.get_remote_address()

        # Assert
        mock_tcp_socket.getpeername.assert_not_called()

    async def test____get_remote_address____client_closed(
        self,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange
        await client_connected_or_not.aclose()
        assert client_connected_or_not.is_closing()

        # Act
        with pytest.raises(ClientClosedError):
            client_connected_or_not.get_remote_address()

        # Assert
        mock_tcp_socket.getpeername.assert_not_called()

    @pytest.mark.usefixtures("setup_producer_mock")
    async def test____send_packet____send_bytes_to_socket(
        self,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_tcp_socket: MagicMock,
        mock_stream_socket_adapter: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        await client_connected_or_not.send_packet(mocker.sentinel.packet)

        # Assert
        mock_stream_protocol.generate_chunks.assert_called_once_with(mocker.sentinel.packet)
        mock_stream_socket_adapter.send_all_from_iterable.assert_called_once()
        mock_stream_socket_adapter.send_all.assert_awaited_once_with(b"packet\n")
        mock_tcp_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_ERROR)

    @pytest.mark.usefixtures("setup_producer_mock")
    async def test____send_packet____raise_error_saved_in_SO_ERROR_option(
        self,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_tcp_socket: MagicMock,
        mock_stream_socket_adapter: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        mock_tcp_socket.getsockopt.return_value = errno.EBUSY

        # Act
        with pytest.raises(OSError) as exc_info:
            await client_connected_or_not.send_packet(mocker.sentinel.packet)

        # Assert
        assert exc_info.value.errno == errno.EBUSY
        mock_stream_protocol.generate_chunks.assert_called_once_with(mocker.sentinel.packet)
        mock_stream_socket_adapter.send_all_from_iterable.assert_called_once()
        mock_stream_socket_adapter.send_all.assert_awaited_once_with(b"packet\n")
        mock_tcp_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_ERROR)

    @pytest.mark.usefixtures("setup_producer_mock")
    async def test____send_packet____closed_client_error(
        self,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_tcp_socket: MagicMock,
        mock_stream_socket_adapter: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        await client_connected_or_not.aclose()
        assert client_connected_or_not.is_closing()

        # Act
        with pytest.raises(ClientClosedError):
            await client_connected_or_not.send_packet(mocker.sentinel.packet)

        # Assert
        mock_stream_protocol.generate_chunks.assert_not_called()
        mock_stream_socket_adapter.send_all_from_iterable.assert_not_called()
        mock_stream_socket_adapter.send_all.assert_not_called()
        mock_tcp_socket.getsockopt.assert_not_called()

    @pytest.mark.usefixtures("setup_producer_mock")
    async def test____send_packet____unexpected_socket_close(
        self,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_tcp_socket: MagicMock,
        mock_stream_socket_adapter: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_socket_adapter.is_closing.return_value = True

        # Act
        with pytest.raises(ClientClosedError):
            await client_connected_or_not.send_packet(mocker.sentinel.packet)

        # Assert
        mock_stream_protocol.generate_chunks.assert_not_called()
        mock_stream_socket_adapter.send_all_from_iterable.assert_not_called()
        mock_stream_socket_adapter.send_all.assert_not_awaited()
        mock_tcp_socket.getsockopt.assert_not_called()

    @pytest.mark.usefixtures("setup_producer_mock")
    async def test____send_packet____convert_connection_errors(
        self,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_tcp_socket: MagicMock,
        mock_stream_socket_adapter: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_socket_adapter.send_all.side_effect = ConnectionError

        # Act
        with pytest.raises(ConnectionAbortedError):
            await client_connected_or_not.send_packet(mocker.sentinel.packet)

        # Assert
        mock_stream_protocol.generate_chunks.assert_called_once_with(mocker.sentinel.packet)
        mock_stream_socket_adapter.send_all_from_iterable.assert_called_once()
        mock_stream_socket_adapter.send_all.assert_awaited_once_with(b"packet\n")
        mock_tcp_socket.getsockopt.assert_not_called()

    @pytest.mark.usefixtures("setup_producer_mock")
    @pytest.mark.parametrize("closed_socket_errno", sorted(CLOSED_SOCKET_ERRNOS), ids=errno.errorcode.__getitem__)
    async def test____send_packet____convert_closed_socket_error(
        self,
        closed_socket_errno: int,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_tcp_socket: MagicMock,
        mock_stream_socket_adapter: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_socket_adapter.send_all.side_effect = OSError(closed_socket_errno, os.strerror(closed_socket_errno))

        # Act
        with pytest.raises(ClientClosedError):
            await client_connected_or_not.send_packet(mocker.sentinel.packet)

        # Assert
        mock_stream_protocol.generate_chunks.assert_called_once_with(mocker.sentinel.packet)
        mock_stream_socket_adapter.send_all_from_iterable.assert_called_once()
        mock_stream_socket_adapter.send_all.assert_awaited_once_with(b"packet\n")
        mock_tcp_socket.getsockopt.assert_not_called()

    @pytest.mark.usefixtures("setup_producer_mock")
    async def test____send_eof____socket_send_eof(
        self,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_stream_socket_adapter: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_socket_adapter.send_eof.return_value = None

        # Act
        await client_connected_or_not.send_eof()

        # Assert
        mock_stream_socket_adapter.send_eof.assert_awaited_once_with()
        with pytest.raises(RuntimeError, match=r"^send_eof\(\) has been called earlier$"):
            await client_connected_or_not.send_packet(mocker.sentinel.packet)
        mock_stream_protocol.generate_chunks.assert_not_called()
        mock_stream_socket_adapter.send_all_from_iterable.assert_not_called()
        mock_stream_socket_adapter.send_all.assert_not_awaited()

    @pytest.mark.usefixtures("setup_producer_mock")
    async def test____send_eof____closed_client(
        self,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_stream_socket_adapter: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_socket_adapter.send_eof.return_value = None
        await client_connected_or_not.aclose()

        # Act
        await client_connected_or_not.send_eof()

        # Assert
        mock_stream_socket_adapter.send_eof.assert_not_awaited()

    @pytest.mark.usefixtures("setup_producer_mock")
    async def test____send_eof____unexpected_socket_close(
        self,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_stream_socket_adapter: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_socket_adapter.send_eof.return_value = None
        mock_stream_socket_adapter.is_closing.return_value = True

        # Act
        await client_connected_or_not.send_eof()

        # Assert
        mock_stream_socket_adapter.send_eof.assert_not_awaited()

    @pytest.mark.usefixtures("setup_producer_mock")
    async def test____send_eof____idempotent(
        self,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_stream_socket_adapter: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_socket_adapter.send_eof.return_value = None
        await client_connected_or_not.send_eof()

        # Act
        await client_connected_or_not.send_eof()

        # Assert
        mock_stream_socket_adapter.send_eof.assert_awaited_once()

    @pytest.mark.usefixtures("setup_consumer_mock")
    async def test____recv_packet____receive_bytes_from_socket(
        self,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_stream_socket_adapter: MagicMock,
        mock_stream_data_consumer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_socket_adapter.recv.side_effect = [b"packet\n"]

        # Act
        packet: Any = await client_connected_or_not.recv_packet()

        # Assert
        mock_stream_socket_adapter.recv.assert_awaited_once_with(DEFAULT_STREAM_BUFSIZE)
        mock_stream_data_consumer.feed.assert_called_once_with(b"packet\n")
        assert packet is mocker.sentinel.packet

    @pytest.mark.usefixtures("setup_consumer_mock")
    async def test____recv_packet____partial_data(
        self,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_stream_socket_adapter: MagicMock,
        mock_stream_data_consumer: MagicMock,
        mock_backend: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_socket_adapter.recv.side_effect = [b"pac", b"ket\n"]

        # Act
        packet: Any = await client_connected_or_not.recv_packet()

        # Assert
        mock_backend.coro_yield.assert_not_awaited()
        assert mock_stream_socket_adapter.recv.call_args_list == [mocker.call(DEFAULT_STREAM_BUFSIZE) for _ in range(2)]
        assert mock_stream_data_consumer.feed.call_args_list == [mocker.call(b"pac"), mocker.call(b"ket\n")]
        assert packet is mocker.sentinel.packet

    @pytest.mark.usefixtures("setup_consumer_mock")
    async def test____recv_packet____extra_data(
        self,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_stream_socket_adapter: MagicMock,
        mock_stream_data_consumer: MagicMock,
        mock_backend: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_socket_adapter.recv.side_effect = [b"packet_1\npacket_2\n"]

        # Act
        packet_1: Any = await client_connected_or_not.recv_packet()
        packet_2: Any = await client_connected_or_not.recv_packet()

        # Assert
        mock_stream_socket_adapter.recv.assert_awaited_once()
        mock_stream_data_consumer.feed.assert_called_once_with(b"packet_1\npacket_2\n")
        mock_backend.coro_yield.assert_not_awaited()
        assert packet_1 is mocker.sentinel.packet_1
        assert packet_2 is mocker.sentinel.packet_2

    @pytest.mark.usefixtures("setup_consumer_mock")
    async def test____recv_packet____eof_error____default(
        self,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_stream_socket_adapter: MagicMock,
        mock_stream_data_consumer: MagicMock,
        mock_backend: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_socket_adapter.recv.side_effect = [b""]

        # Act
        with pytest.raises(ConnectionAbortedError):
            _ = await client_connected_or_not.recv_packet()

        # Assert
        mock_stream_socket_adapter.recv.assert_awaited_once_with(DEFAULT_STREAM_BUFSIZE)
        mock_stream_data_consumer.feed.assert_not_called()
        mock_backend.coro_yield.assert_not_awaited()

    @pytest.mark.usefixtures("setup_consumer_mock")
    async def test____recv_packet____protocol_parse_error(
        self,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_stream_socket_adapter: MagicMock,
        mock_backend: MagicMock,
        mock_stream_data_consumer: MagicMock,
    ) -> None:
        # Arrange

        mock_stream_socket_adapter.recv.side_effect = [b"packet\n"]
        expected_error = StreamProtocolParseError(b"", IncrementalDeserializeError("Sorry", b""))
        mock_stream_data_consumer.__next__.side_effect = [StopIteration, expected_error]

        # Act
        with pytest.raises(StreamProtocolParseError) as exc_info:
            _ = await client_connected_or_not.recv_packet()
        exception = exc_info.value

        # Assert
        mock_stream_socket_adapter.recv.assert_awaited_once_with(DEFAULT_STREAM_BUFSIZE)
        mock_stream_data_consumer.feed.assert_called_once_with(b"packet\n")
        mock_backend.coro_yield.assert_not_awaited()
        assert exception is expected_error

    @pytest.mark.usefixtures("setup_consumer_mock")
    async def test____recv_packet____closed_client_error(
        self,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_stream_socket_adapter: MagicMock,
        mock_backend: MagicMock,
        mock_stream_data_consumer: MagicMock,
    ) -> None:
        # Arrange
        await client_connected_or_not.aclose()
        assert client_connected_or_not.is_closing()

        # Act
        with pytest.raises(ClientClosedError):
            _ = await client_connected_or_not.recv_packet()

        # Assert
        mock_stream_data_consumer.feed.assert_not_called()
        mock_stream_socket_adapter.recv.assert_not_called()
        mock_backend.coro_yield.assert_not_awaited()

    @pytest.mark.usefixtures("setup_consumer_mock")
    async def test____recv_packet____unexpected_socket_close(
        self,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_stream_socket_adapter: MagicMock,
        mock_backend: MagicMock,
        mock_stream_data_consumer: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_socket_adapter.is_closing.return_value = True

        # Act
        with pytest.raises(ClientClosedError):
            _ = await client_connected_or_not.recv_packet()

        # Assert
        mock_stream_data_consumer.feed.assert_not_called()
        mock_stream_socket_adapter.recv.assert_not_called()
        mock_backend.coro_yield.assert_not_awaited()

    @pytest.mark.usefixtures("setup_consumer_mock")
    async def test____recv_packet____convert_connection_errors(
        self,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_stream_socket_adapter: MagicMock,
        mock_backend: MagicMock,
        mock_stream_data_consumer: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_socket_adapter.recv.side_effect = ConnectionError

        # Act
        with pytest.raises(ConnectionAbortedError):
            _ = await client_connected_or_not.recv_packet()

        # Assert
        mock_stream_socket_adapter.recv.assert_awaited_once_with(DEFAULT_STREAM_BUFSIZE)
        mock_stream_data_consumer.feed.assert_not_called()
        mock_backend.coro_yield.assert_not_awaited()

    @pytest.mark.usefixtures("setup_consumer_mock")
    @pytest.mark.parametrize("closed_socket_errno", sorted(CLOSED_SOCKET_ERRNOS), ids=errno.errorcode.__getitem__)
    async def test____recv_packet____convert_closed_socket_errors(
        self,
        closed_socket_errno: int,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_stream_socket_adapter: MagicMock,
        mock_backend: MagicMock,
        mock_stream_data_consumer: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_socket_adapter.recv.side_effect = OSError(closed_socket_errno, os.strerror(closed_socket_errno))

        # Act
        with pytest.raises(ClientClosedError):
            _ = await client_connected_or_not.recv_packet()

        # Assert
        mock_stream_socket_adapter.recv.assert_awaited_once_with(DEFAULT_STREAM_BUFSIZE)
        mock_stream_data_consumer.feed.assert_not_called()
        mock_backend.coro_yield.assert_not_awaited()

    @pytest.mark.usefixtures("setup_producer_mock", "setup_consumer_mock")
    async def test____special_case____send_packet____eof_error____still_try_socket_send(
        self,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_stream_socket_adapter: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_socket_adapter.recv.side_effect = [b""]
        with pytest.raises(ConnectionAbortedError):
            _ = await client_connected_or_not.recv_packet()

        mock_stream_socket_adapter.recv.reset_mock()

        # Act
        await client_connected_or_not.send_packet(mocker.sentinel.packet)

        # Assert
        mock_stream_protocol.generate_chunks.assert_called_with(mocker.sentinel.packet)
        mock_stream_socket_adapter.send_all_from_iterable.assert_called()
        mock_stream_socket_adapter.send_all.assert_called_with(b"packet\n")

    @pytest.mark.usefixtures("setup_consumer_mock")
    async def test____special_case____recv_packet____eof_error____do_not_try_socket_recv_on_next_call(
        self,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_stream_socket_adapter: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_socket_adapter.recv.side_effect = [b""]
        with pytest.raises(ConnectionAbortedError):
            _ = await client_connected_or_not.recv_packet()

        mock_stream_socket_adapter.recv.reset_mock()

        # Act
        with pytest.raises(ConnectionAbortedError):
            _ = await client_connected_or_not.recv_packet()

        # Assert
        mock_stream_socket_adapter.recv.assert_not_called()

    @pytest.mark.usefixtures("setup_producer_mock", "setup_consumer_mock")
    async def test____special_case____separate_send_and_receive_locks(
        self,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_stream_socket_adapter: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        async def recv_side_effect(bufsize: int) -> bytes:
            await client_connected_or_not.send_packet(mocker.sentinel.packet)
            return b""

        mock_stream_socket_adapter.recv = mocker.MagicMock(side_effect=recv_side_effect)

        # Act
        with pytest.raises(ConnectionAbortedError):
            _ = await client_connected_or_not.recv_packet()

        # Assert
        mock_stream_protocol.generate_chunks.assert_called_with(mocker.sentinel.packet)
        mock_stream_socket_adapter.send_all_from_iterable.assert_called()
        mock_stream_socket_adapter.send_all.assert_called_with(b"packet\n")

    @pytest.mark.usefixtures("setup_producer_mock", "setup_consumer_mock")
    @pytest.mark.parametrize("ssl_shared_lock", [None, False, True], ids=lambda p: f"ssl_shared_lock=={p}")
    async def test____special_case____separate_send_and_receive_locks____ssl(
        self,
        remote_address: tuple[str, int],
        ssl_shared_lock: bool | None,
        mock_stream_socket_adapter: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_backend: MagicMock,
        mock_ssl_context: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        client: AsyncTCPNetworkClient[Any, Any] = AsyncTCPNetworkClient(
            remote_address,
            protocol=mock_stream_protocol,
            ssl=mock_ssl_context,
            server_hostname="server_hostname",
            ssl_shared_lock=ssl_shared_lock,
            backend=mock_backend,
        )
        await client.wait_connected()

        if ssl_shared_lock is None:
            ssl_shared_lock = True  # Should be true by default

        async def recv_side_effect(bufsize: int) -> bytes:
            with pytest.raises(AsyncDummyLock.AcquireFailed) if ssl_shared_lock else contextlib.nullcontext():
                await client.send_packet(mocker.sentinel.packet)
            return b""

        mock_stream_socket_adapter.recv = mocker.MagicMock(side_effect=recv_side_effect)

        # Act
        with pytest.raises(ConnectionAbortedError):
            _ = await client.recv_packet()

        # Assert
        if ssl_shared_lock:
            mock_stream_protocol.generate_chunks.assert_not_called()
            mock_stream_socket_adapter.send_all_from_iterable.assert_not_called()
            mock_stream_socket_adapter.send_all.assert_not_called()
        else:
            mock_stream_protocol.generate_chunks.assert_called_with(mocker.sentinel.packet)
            mock_stream_socket_adapter.send_all_from_iterable.assert_called()
            mock_stream_socket_adapter.send_all.assert_called_with(b"packet\n")

    async def test____get_backend____default(
        self,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        assert client_connected_or_not.get_backend() is mock_backend
