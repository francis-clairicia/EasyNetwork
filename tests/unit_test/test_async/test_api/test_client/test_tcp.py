from __future__ import annotations

import contextlib
import errno
import os
import ssl
from collections.abc import AsyncIterator
from socket import AF_INET6, IPPROTO_TCP, SO_ERROR, SO_KEEPALIVE, SOL_SOCKET, TCP_NODELAY
from typing import TYPE_CHECKING, Any

from easynetwork.clients.async_tcp import AsyncTCPNetworkClient
from easynetwork.exceptions import ClientClosedError, IncrementalDeserializeError, StreamProtocolParseError
from easynetwork.lowlevel._stream import StreamDataConsumer
from easynetwork.lowlevel.api_async.transports.tls import AsyncTLSStreamTransport
from easynetwork.lowlevel.constants import CLOSED_SOCKET_ERRNOS, DEFAULT_STREAM_BUFSIZE
from easynetwork.lowlevel.socket import IPv4SocketAddress, IPv6SocketAddress, SocketProxy, _get_socket_extra
from easynetwork.lowlevel.typed_attr import TypedAttributeProvider

import pytest
import pytest_asyncio

if TYPE_CHECKING:
    from unittest.mock import AsyncMock, MagicMock

    from pytest_mock import MockerFixture

    from .....pytest_plugins.async_finalizer import AsyncFinalizer

from ....base import UNSUPPORTED_FAMILIES, BaseTestWithStreamProtocol
from .base import BaseTestClient


@pytest.mark.asyncio
@pytest.mark.filterwarnings("ignore::ResourceWarning:easynetwork.lowlevel.api_async.endpoints.stream")
class TestAsyncTCPNetworkClient(BaseTestClient, BaseTestWithStreamProtocol):
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

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_tls_wrap_transport(mocker: MockerFixture) -> AsyncMock:
        return mocker.patch.object(AsyncTLSStreamTransport, "wrap", autospec=True)

    @pytest.fixture
    @staticmethod
    def stream_protocol_mode(request: pytest.FixtureRequest) -> str:
        return "data"

    @pytest.fixture
    @staticmethod
    def mock_stream_data_consumer(mock_stream_protocol: MagicMock, mocker: MockerFixture) -> MagicMock:
        return mocker.NonCallableMagicMock(spec=StreamDataConsumer, wraps=StreamDataConsumer(mock_stream_protocol))

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_stream_data_consumer_cls(mocker: MockerFixture, mock_stream_data_consumer: MagicMock) -> MagicMock:
        return mocker.patch("easynetwork.lowlevel._stream.StreamDataConsumer", return_value=mock_stream_data_consumer)

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
        mock_tls_wrap_transport: AsyncMock,
    ) -> None:
        mock_tcp_socket.family = socket_family
        mock_tcp_socket.getsockopt.return_value = 0  # Needed for tests dealing with send_packet()
        del mock_tcp_socket.sendall
        del mock_tcp_socket.recv

        mock_backend.create_tcp_connection.return_value = mock_stream_socket_adapter
        mock_backend.wrap_stream_socket.return_value = mock_stream_socket_adapter
        mock_tls_wrap_transport.return_value = mock_stream_socket_adapter

        mock_stream_socket_adapter.extra_attributes = _get_socket_extra(mock_tcp_socket, wrap_in_proxy=False)
        mock_stream_socket_adapter.extra.side_effect = TypedAttributeProvider.extra.__get__(mock_stream_socket_adapter)

    @pytest_asyncio.fixture
    @staticmethod
    async def client_not_connected(
        mock_backend: MagicMock,
        remote_address: tuple[str, int],
        mock_stream_protocol: MagicMock,
    ) -> AsyncIterator[AsyncTCPNetworkClient[Any, Any]]:
        client: AsyncTCPNetworkClient[Any, Any] = AsyncTCPNetworkClient(remote_address, mock_stream_protocol, mock_backend)
        assert not client.is_connected()
        async with contextlib.aclosing(client):
            yield client

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
        async_finalizer: AsyncFinalizer,
        remote_address: tuple[str, int],
        mock_tcp_socket: MagicMock,
        mock_backend: MagicMock,
        mock_stream_data_consumer_cls: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_tls_wrap_transport: AsyncMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        client: AsyncTCPNetworkClient[Any, Any] = AsyncTCPNetworkClient(
            remote_address,
            protocol=mock_stream_protocol,
            backend=mock_backend,
            local_address=mocker.sentinel.local_address,
            happy_eyeballs_delay=mocker.sentinel.happy_eyeballs_delay,
        )
        async_finalizer.add_finalizer(client.aclose)
        await client.wait_connected()

        # Assert
        mock_stream_data_consumer_cls.assert_called_once_with(mock_stream_protocol)
        mock_backend.create_tcp_connection.assert_awaited_once_with(
            *remote_address,
            local_address=mocker.sentinel.local_address,
            happy_eyeballs_delay=mocker.sentinel.happy_eyeballs_delay,
        )
        mock_tls_wrap_transport.assert_not_awaited()
        assert mock_tcp_socket.mock_calls == [
            mocker.call.setsockopt(IPPROTO_TCP, TCP_NODELAY, True),
            mocker.call.setsockopt(SOL_SOCKET, SO_KEEPALIVE, True),
        ]
        assert isinstance(client.socket, SocketProxy)

    async def test____dunder_init____use_given_socket(
        self,
        async_finalizer: AsyncFinalizer,
        mock_tcp_socket: MagicMock,
        mock_backend: MagicMock,
        mock_stream_data_consumer_cls: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_tls_wrap_transport: AsyncMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        client: AsyncTCPNetworkClient[Any, Any] = AsyncTCPNetworkClient(
            mock_tcp_socket,
            protocol=mock_stream_protocol,
            backend=mock_backend,
        )
        async_finalizer.add_finalizer(client.aclose)
        await client.wait_connected()

        # Assert
        mock_stream_data_consumer_cls.assert_called_once_with(mock_stream_protocol)
        mock_backend.wrap_stream_socket.assert_awaited_once_with(mock_tcp_socket)
        mock_tls_wrap_transport.assert_not_awaited()
        assert mock_tcp_socket.mock_calls == [
            mocker.call.getpeername(),
            mocker.call.setsockopt(IPPROTO_TCP, TCP_NODELAY, True),
            mocker.call.setsockopt(SOL_SOCKET, SO_KEEPALIVE, True),
        ]
        assert isinstance(client.socket, SocketProxy)

    async def test____dunder_init____use_given_socket____error_no_remote_address(
        self,
        mock_tcp_socket: MagicMock,
        mock_backend: MagicMock,
        mock_stream_protocol: MagicMock,
    ) -> None:
        # Arrange
        self.configure_socket_mock_to_raise_ENOTCONN(mock_tcp_socket)

        # Act
        with pytest.raises(OSError) as exc_info:
            _ = AsyncTCPNetworkClient(
                mock_tcp_socket,
                protocol=mock_stream_protocol,
                backend=mock_backend,
            )

        # Assert
        assert exc_info.value.errno == errno.ENOTCONN

    @pytest.mark.parametrize("socket_family", list(UNSUPPORTED_FAMILIES), indirect=True)
    @pytest.mark.parametrize("use_ssl", [False, True], ids=lambda p: f"use_ssl=={p}")
    async def test____dunder_init____use_given_socket____invalid_socket_family(
        self,
        use_ssl: bool,
        mock_backend: MagicMock,
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
                backend=mock_backend,
                ssl=ssl_context,
                server_hostname=server_hostname,
            )

    async def test____dunder_init____invalid_first_argument____invalid_object(
        self,
        mock_stream_protocol: MagicMock,
        mock_backend: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        invalid_object = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Invalid arguments$"):
            _ = AsyncTCPNetworkClient(
                invalid_object,
                protocol=mock_stream_protocol,
                backend=mock_backend,
            )

    async def test____dunder_init____invalid_first_argument____invalid_host_port_pair(
        self,
        mock_stream_protocol: MagicMock,
        mock_backend: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        invalid_host = mocker.NonCallableMagicMock(spec=object)
        invalid_port = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Invalid arguments$"):
            _ = AsyncTCPNetworkClient(
                (invalid_host, invalid_port),
                protocol=mock_stream_protocol,
                backend=mock_backend,
            )

    @pytest.mark.parametrize("use_socket", [False, True], ids=lambda p: f"use_socket=={p}")
    async def test____dunder_init____protocol____invalid_value(
        self,
        request: pytest.FixtureRequest,
        use_socket: bool,
        mock_datagram_protocol: MagicMock,
        mock_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a StreamProtocol or a BufferedStreamProtocol object, got .*$"):
            if use_socket:
                _ = AsyncTCPNetworkClient(
                    request.getfixturevalue("mock_tcp_socket"),
                    mock_datagram_protocol,
                    mock_backend,
                )
            else:
                _ = AsyncTCPNetworkClient(
                    request.getfixturevalue("remote_address"),
                    mock_datagram_protocol,
                    mock_backend,
                )

    @pytest.mark.parametrize("use_socket", [False, True], ids=lambda p: f"use_socket=={p}")
    async def test____dunder_init____backend____invalid_value(
        self,
        request: pytest.FixtureRequest,
        use_socket: bool,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        invalid_backend = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected either a string literal or a backend instance, got .*$"):
            if use_socket:
                _ = AsyncTCPNetworkClient(
                    request.getfixturevalue("mock_tcp_socket"),
                    mock_stream_protocol,
                    invalid_backend,
                )
            else:
                _ = AsyncTCPNetworkClient(
                    request.getfixturevalue("remote_address"),
                    mock_stream_protocol,
                    invalid_backend,
                )

    @pytest.mark.parametrize("max_recv_size", [0, -1, 10.4], ids=lambda p: f"max_recv_size=={p}")
    @pytest.mark.parametrize("use_socket", [False, True], ids=lambda p: f"use_socket=={p}")
    async def test____dunder_init____max_recv_size____invalid_value(
        self,
        request: pytest.FixtureRequest,
        max_recv_size: Any,
        use_socket: bool,
        mock_stream_protocol: MagicMock,
        mock_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^'max_recv_size' must be a strictly positive integer$"):
            if use_socket:
                _ = AsyncTCPNetworkClient(
                    request.getfixturevalue("mock_tcp_socket"),
                    mock_stream_protocol,
                    mock_backend,
                    max_recv_size=max_recv_size,
                )
            else:
                _ = AsyncTCPNetworkClient(
                    request.getfixturevalue("remote_address"),
                    mock_stream_protocol,
                    mock_backend,
                    max_recv_size=max_recv_size,
                )

    @pytest.mark.parametrize("use_socket", [False, True], ids=lambda p: f"use_socket=={p}")
    async def test____dunder_init____ssl(
        self,
        async_finalizer: AsyncFinalizer,
        use_socket: bool,
        remote_address: tuple[str, int],
        mock_tcp_socket: MagicMock,
        mock_backend: MagicMock,
        mock_stream_data_consumer_cls: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_ssl_context: MagicMock,
        mock_ssl_create_default_context: MagicMock,
        mock_tls_wrap_transport: AsyncMock,
        mock_stream_socket_adapter: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        client: AsyncTCPNetworkClient[Any, Any]
        if use_socket:
            client = AsyncTCPNetworkClient(
                mock_tcp_socket,
                protocol=mock_stream_protocol,
                backend=mock_backend,
                ssl=mock_ssl_context,
                server_hostname="server_hostname",
                ssl_handshake_timeout=mocker.sentinel.ssl_handshake_timeout,
                ssl_shutdown_timeout=mocker.sentinel.ssl_shutdown_timeout,
                ssl_standard_compatible=mocker.sentinel.ssl_standard_compatible,
            )
        else:
            client = AsyncTCPNetworkClient(
                remote_address,
                protocol=mock_stream_protocol,
                backend=mock_backend,
                ssl=mock_ssl_context,
                server_hostname="server_hostname",
                ssl_handshake_timeout=mocker.sentinel.ssl_handshake_timeout,
                ssl_shutdown_timeout=mocker.sentinel.ssl_shutdown_timeout,
                ssl_standard_compatible=mocker.sentinel.ssl_standard_compatible,
                local_address=mocker.sentinel.local_address,
                happy_eyeballs_delay=mocker.sentinel.happy_eyeballs_delay,
            )
        async_finalizer.add_finalizer(client.aclose)
        await client.wait_connected()

        # Assert
        mock_stream_data_consumer_cls.assert_called_once_with(mock_stream_protocol)
        mock_ssl_create_default_context.assert_not_called()
        if use_socket:
            mock_backend.wrap_stream_socket.assert_awaited_once_with(mock_tcp_socket)
            assert mock_tcp_socket.mock_calls == [
                mocker.call.getpeername(),
                mocker.call.setsockopt(IPPROTO_TCP, TCP_NODELAY, True),
                mocker.call.setsockopt(SOL_SOCKET, SO_KEEPALIVE, True),
            ]
        else:
            mock_backend.create_tcp_connection.assert_awaited_once_with(
                *remote_address,
                local_address=mocker.sentinel.local_address,
                happy_eyeballs_delay=mocker.sentinel.happy_eyeballs_delay,
            )
            assert mock_tcp_socket.mock_calls == [
                mocker.call.setsockopt(IPPROTO_TCP, TCP_NODELAY, True),
                mocker.call.setsockopt(SOL_SOCKET, SO_KEEPALIVE, True),
            ]
        mock_tls_wrap_transport.assert_awaited_once_with(
            mock_stream_socket_adapter,
            mock_ssl_context,
            server_side=False,
            server_hostname="server_hostname",
            handshake_timeout=mocker.sentinel.ssl_handshake_timeout,
            shutdown_timeout=mocker.sentinel.ssl_shutdown_timeout,
            standard_compatible=mocker.sentinel.ssl_standard_compatible,
        )
        assert isinstance(client.socket, SocketProxy)

    @pytest.mark.parametrize("use_socket", [False, True], ids=lambda p: f"use_socket=={p}")
    async def test____dunder_init____ssl____default_values(
        self,
        async_finalizer: AsyncFinalizer,
        use_socket: bool,
        remote_address: tuple[str, int],
        mock_backend: MagicMock,
        mock_tcp_socket: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_ssl_context: MagicMock,
        mock_tls_wrap_transport: AsyncMock,
        mock_stream_socket_adapter: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        client: AsyncTCPNetworkClient[Any, Any]
        if use_socket:
            client = AsyncTCPNetworkClient(
                mock_tcp_socket,
                protocol=mock_stream_protocol,
                backend=mock_backend,
                ssl=mock_ssl_context,
                server_hostname="server_hostname",
            )
        else:
            client = AsyncTCPNetworkClient(
                remote_address,
                protocol=mock_stream_protocol,
                backend=mock_backend,
                ssl=mock_ssl_context,
                server_hostname="server_hostname",
                local_address=mocker.sentinel.local_address,
                happy_eyeballs_delay=mocker.sentinel.happy_eyeballs_delay,
            )
        async_finalizer.add_finalizer(client.aclose)
        await client.wait_connected()

        # Assert
        mock_tls_wrap_transport.assert_awaited_once_with(
            mock_stream_socket_adapter,
            mock_ssl_context,
            server_side=False,
            server_hostname="server_hostname",
            handshake_timeout=None,
            shutdown_timeout=None,
            standard_compatible=True,
        )

    @pytest.mark.parametrize("use_socket", [False, True], ids=lambda p: f"use_socket=={p}")
    @pytest.mark.parametrize(
        "ssl_parameter",
        [
            "server_hostname",
            "ssl_handshake_timeout",
            "ssl_shutdown_timeout",
            "ssl_standard_compatible",
        ],
    )
    async def test____dunder_init____ssl____useless_parameter_if_no_context(
        self,
        ssl_parameter: str,
        use_socket: bool,
        remote_address: tuple[str, int],
        mock_tcp_socket: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_backend: MagicMock,
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
                    backend=mock_backend,
                    ssl=None,
                    **kwargs,
                )
            else:
                _ = AsyncTCPNetworkClient(
                    remote_address,
                    protocol=mock_stream_protocol,
                    backend=mock_backend,
                    ssl=None,
                    **kwargs,
                )

    @pytest.mark.parametrize("use_socket", [False, True], ids=lambda p: f"use_socket=={p}")
    async def test____dunder_init____ssl____server_hostname____do_not_disable_hostname_check_for_external_context(
        self,
        async_finalizer: AsyncFinalizer,
        use_socket: bool,
        remote_address: tuple[str, int],
        mock_backend: MagicMock,
        mock_tcp_socket: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_ssl_context: MagicMock,
        mock_tls_wrap_transport: AsyncMock,
        mock_stream_socket_adapter: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        check_hostname_by_default: bool = mock_ssl_context.check_hostname
        assert check_hostname_by_default

        # Act
        client: AsyncTCPNetworkClient[Any, Any]
        if use_socket:
            client = AsyncTCPNetworkClient(
                mock_tcp_socket,
                protocol=mock_stream_protocol,
                backend=mock_backend,
                ssl=mock_ssl_context,
                server_hostname="",
                ssl_handshake_timeout=mocker.sentinel.ssl_handshake_timeout,
                ssl_shutdown_timeout=mocker.sentinel.ssl_shutdown_timeout,
                ssl_standard_compatible=mocker.sentinel.ssl_standard_compatible,
            )
        else:
            client = AsyncTCPNetworkClient(
                remote_address,
                protocol=mock_stream_protocol,
                backend=mock_backend,
                ssl=mock_ssl_context,
                server_hostname="",
                ssl_handshake_timeout=mocker.sentinel.ssl_handshake_timeout,
                ssl_shutdown_timeout=mocker.sentinel.ssl_shutdown_timeout,
                ssl_standard_compatible=mocker.sentinel.ssl_standard_compatible,
                local_address=mocker.sentinel.local_address,
                happy_eyeballs_delay=mocker.sentinel.happy_eyeballs_delay,
            )
        async_finalizer.add_finalizer(client.aclose)
        await client.wait_connected()

        # Assert
        mock_tls_wrap_transport.assert_awaited_once_with(
            mock_stream_socket_adapter,
            mock_ssl_context,
            server_side=False,
            server_hostname=None,
            handshake_timeout=mocker.sentinel.ssl_handshake_timeout,
            shutdown_timeout=mocker.sentinel.ssl_shutdown_timeout,
            standard_compatible=mocker.sentinel.ssl_standard_compatible,
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
                backend=mock_backend,
                ssl=mock_ssl_context,
                server_hostname=None,
                ssl_handshake_timeout=mocker.sentinel.ssl_handshake_timeout,
                ssl_shutdown_timeout=mocker.sentinel.ssl_shutdown_timeout,
                ssl_standard_compatible=mocker.sentinel.ssl_standard_compatible,
            )

    @pytest.mark.parametrize("use_socket", [False, True], ids=lambda p: f"use_socket=={p}")
    @pytest.mark.parametrize("OP_IGNORE_UNEXPECTED_EOF", [False, True], ids=lambda p: f"OP_IGNORE_UNEXPECTED_EOF=={p}")
    async def test____dunder_init____ssl____create_default_context(
        self,
        async_finalizer: AsyncFinalizer,
        use_socket: bool,
        OP_IGNORE_UNEXPECTED_EOF: bool,
        remote_address: tuple[str, int],
        mock_backend: MagicMock,
        mock_tcp_socket: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_ssl_context: MagicMock,
        mock_ssl_create_default_context: MagicMock,
        mock_tls_wrap_transport: AsyncMock,
        mock_stream_socket_adapter: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        if not OP_IGNORE_UNEXPECTED_EOF:
            monkeypatch.delattr("ssl.OP_IGNORE_UNEXPECTED_EOF", raising=False)
        elif not hasattr(ssl, "OP_IGNORE_UNEXPECTED_EOF"):
            pytest.skip("ssl.OP_IGNORE_UNEXPECTED_EOF not defined")

        # Act
        client: AsyncTCPNetworkClient[Any, Any]
        if use_socket:
            client = AsyncTCPNetworkClient(
                mock_tcp_socket,
                protocol=mock_stream_protocol,
                backend=mock_backend,
                ssl=True,
                server_hostname="server_hostname",
                ssl_handshake_timeout=mocker.sentinel.ssl_handshake_timeout,
                ssl_shutdown_timeout=mocker.sentinel.ssl_shutdown_timeout,
                ssl_standard_compatible=mocker.sentinel.ssl_standard_compatible,
            )
        else:
            client = AsyncTCPNetworkClient(
                remote_address,
                protocol=mock_stream_protocol,
                backend=mock_backend,
                ssl=True,
                server_hostname="server_hostname",
                ssl_handshake_timeout=mocker.sentinel.ssl_handshake_timeout,
                ssl_shutdown_timeout=mocker.sentinel.ssl_shutdown_timeout,
                ssl_standard_compatible=mocker.sentinel.ssl_standard_compatible,
                local_address=mocker.sentinel.local_address,
                happy_eyeballs_delay=mocker.sentinel.happy_eyeballs_delay,
            )
        async_finalizer.add_finalizer(client.aclose)
        await client.wait_connected()

        # Assert
        mock_ssl_create_default_context.assert_called_once_with()
        mock_tls_wrap_transport.assert_awaited_once_with(
            mock_stream_socket_adapter,
            mock_ssl_context,
            server_side=False,
            server_hostname="server_hostname",
            handshake_timeout=mocker.sentinel.ssl_handshake_timeout,
            shutdown_timeout=mocker.sentinel.ssl_shutdown_timeout,
            standard_compatible=mocker.sentinel.ssl_standard_compatible,
        )

    @pytest.mark.parametrize("use_socket", [False, True], ids=lambda p: f"use_socket=={p}")
    async def test____dunder_init____ssl____create_default_context____disable_hostname_check(
        self,
        async_finalizer: AsyncFinalizer,
        use_socket: bool,
        remote_address: tuple[str, int],
        mock_backend: MagicMock,
        mock_tcp_socket: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_ssl_context: MagicMock,
        mock_ssl_create_default_context: MagicMock,
        mock_tls_wrap_transport: AsyncMock,
        mock_stream_socket_adapter: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        check_hostname_by_default: bool = mock_ssl_context.check_hostname
        assert check_hostname_by_default

        # Act
        client: AsyncTCPNetworkClient[Any, Any]
        if use_socket:
            client = AsyncTCPNetworkClient(
                mock_tcp_socket,
                protocol=mock_stream_protocol,
                backend=mock_backend,
                ssl=True,
                server_hostname="",
                ssl_handshake_timeout=mocker.sentinel.ssl_handshake_timeout,
                ssl_shutdown_timeout=mocker.sentinel.ssl_shutdown_timeout,
                ssl_standard_compatible=mocker.sentinel.ssl_standard_compatible,
            )
        else:
            client = AsyncTCPNetworkClient(
                remote_address,
                protocol=mock_stream_protocol,
                backend=mock_backend,
                ssl=True,
                server_hostname="",
                ssl_handshake_timeout=mocker.sentinel.ssl_handshake_timeout,
                ssl_shutdown_timeout=mocker.sentinel.ssl_shutdown_timeout,
                ssl_standard_compatible=mocker.sentinel.ssl_standard_compatible,
                local_address=mocker.sentinel.local_address,
                happy_eyeballs_delay=mocker.sentinel.happy_eyeballs_delay,
            )
        async_finalizer.add_finalizer(client.aclose)
        await client.wait_connected()

        # Assert
        mock_ssl_create_default_context.assert_called_once_with()
        mock_tls_wrap_transport.assert_awaited_once_with(
            mock_stream_socket_adapter,
            mock_ssl_context,
            server_side=False,
            server_hostname=None,
            handshake_timeout=mocker.sentinel.ssl_handshake_timeout,
            shutdown_timeout=mocker.sentinel.ssl_shutdown_timeout,
            standard_compatible=mocker.sentinel.ssl_standard_compatible,
        )
        assert mock_ssl_context.check_hostname is False

    async def test____dunder_del____ResourceWarning(
        self,
        mock_stream_socket_adapter: MagicMock,
        mock_stream_protocol: MagicMock,
        remote_address: tuple[str, int],
        mock_backend: MagicMock,
    ) -> None:
        client: AsyncTCPNetworkClient[Any, Any] = AsyncTCPNetworkClient(
            remote_address,
            protocol=mock_stream_protocol,
            backend=mock_backend,
        )
        await client.wait_connected()

        # Act & Assert
        with pytest.warns(
            ResourceWarning,
            match=r"^unclosed client .+ pointing to .+ \(and cannot be closed synchronously\)$",
        ):
            del client

        mock_stream_socket_adapter.aclose.assert_not_called()

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
        old_side_effect = mock_stream_socket_adapter.aclose.side_effect
        mock_stream_socket_adapter.aclose.side_effect = fake_cancellation_cls

        # Act
        with pytest.raises(fake_cancellation_cls):
            await client_connected.aclose()
        mock_stream_socket_adapter.aclose.side_effect = old_side_effect

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

    async def test____get_backend____returns_linked_instance(
        self,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        assert client_connected_or_not.backend() is mock_backend

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

    async def test____send_packet____unrelated_ssl_errors(
        self,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_tcp_socket: MagicMock,
        mock_stream_socket_adapter: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_socket_adapter.send_all.side_effect = ssl.SSLError(
            ssl.SSLErrorNumber.SSL_ERROR_INVALID_ERROR_CODE,
            "SOMETHING",
        )

        # Act
        with pytest.raises(ssl.SSLError):
            await client_connected_or_not.send_packet(mocker.sentinel.packet)

        # Assert
        mock_stream_protocol.generate_chunks.assert_called_once_with(mocker.sentinel.packet)
        mock_stream_socket_adapter.send_all_from_iterable.assert_called_once()
        mock_stream_socket_adapter.send_all.assert_awaited_once_with(b"packet\n")
        mock_tcp_socket.getsockopt.assert_not_called()

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
        assert mock_stream_data_consumer.next.call_args_list == [mocker.call(None), mocker.call(b"packet\n")]
        assert packet is mocker.sentinel.packet

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
        assert mock_stream_data_consumer.next.call_args_list == [mocker.call(None), mocker.call(b"pac"), mocker.call(b"ket\n")]
        assert packet is mocker.sentinel.packet

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
        assert mock_stream_data_consumer.next.call_args_list == [
            mocker.call(None),
            mocker.call(b"packet_1\npacket_2\n"),
            mocker.call(None),
        ]
        mock_backend.coro_yield.assert_not_awaited()
        assert packet_1 is mocker.sentinel.packet_1
        assert packet_2 is mocker.sentinel.packet_2

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
        mock_stream_data_consumer.next.assert_called_once_with(None)
        mock_backend.coro_yield.assert_not_awaited()

    async def test____recv_packet____eof_error____ssl(
        self,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_stream_socket_adapter: MagicMock,
        mock_stream_data_consumer: MagicMock,
        mock_backend: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_socket_adapter.recv.side_effect = ssl.SSLEOFError()

        # Act
        with pytest.raises(ConnectionAbortedError):
            _ = await client_connected_or_not.recv_packet()

        # Assert
        mock_stream_socket_adapter.recv.assert_awaited_once_with(DEFAULT_STREAM_BUFSIZE)
        mock_stream_data_consumer.next.assert_called_once_with(None)
        mock_backend.coro_yield.assert_not_awaited()

    async def test____recv_packet____protocol_parse_error(
        self,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_stream_socket_adapter: MagicMock,
        mock_backend: MagicMock,
        mock_stream_data_consumer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        mock_stream_socket_adapter.recv.side_effect = [b"packet\n"]
        expected_error = StreamProtocolParseError(b"", IncrementalDeserializeError("Sorry", b""))
        mock_stream_data_consumer.next.side_effect = [StopIteration, expected_error]

        # Act
        with pytest.raises(StreamProtocolParseError) as exc_info:
            _ = await client_connected_or_not.recv_packet()
        exception = exc_info.value

        # Assert
        mock_stream_socket_adapter.recv.assert_awaited_once_with(DEFAULT_STREAM_BUFSIZE)
        assert mock_stream_data_consumer.next.call_args_list == [mocker.call(None), mocker.call(b"packet\n")]
        mock_backend.coro_yield.assert_not_awaited()
        assert exception is expected_error

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
        mock_stream_data_consumer.next.assert_not_called()
        mock_stream_socket_adapter.recv.assert_not_called()
        mock_backend.coro_yield.assert_not_awaited()

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
        mock_stream_data_consumer.next.assert_not_called()
        mock_stream_socket_adapter.recv.assert_not_called()
        mock_backend.coro_yield.assert_not_awaited()

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
        mock_stream_data_consumer.next.assert_called_once_with(None)
        mock_backend.coro_yield.assert_not_awaited()

    async def test____recv_packet____unrelated_ssl_error(
        self,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_stream_socket_adapter: MagicMock,
        mock_stream_data_consumer: MagicMock,
        mock_backend: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_socket_adapter.recv.side_effect = ssl.SSLError(
            ssl.SSLErrorNumber.SSL_ERROR_INVALID_ERROR_CODE,
            "SOMETHING",
        )

        # Act
        with pytest.raises(ssl.SSLError):
            _ = await client_connected_or_not.recv_packet()

        # Assert
        mock_stream_socket_adapter.recv.assert_awaited_once_with(DEFAULT_STREAM_BUFSIZE)
        mock_stream_data_consumer.next.assert_called_once_with(None)
        mock_backend.coro_yield.assert_not_awaited()

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
        mock_stream_data_consumer.next.assert_called_once_with(None)
        mock_backend.coro_yield.assert_not_awaited()

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

    async def test____special_case____separate_send_and_receive_locks____ssl(
        self,
        async_finalizer: AsyncFinalizer,
        remote_address: tuple[str, int],
        mock_backend: MagicMock,
        mock_stream_socket_adapter: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_ssl_context: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        client: AsyncTCPNetworkClient[Any, Any] = AsyncTCPNetworkClient(
            remote_address,
            protocol=mock_stream_protocol,
            backend=mock_backend,
            ssl=mock_ssl_context,
            server_hostname="server_hostname",
        )
        async_finalizer.add_finalizer(client.aclose)
        await client.wait_connected()

        async def recv_side_effect(bufsize: int) -> bytes:
            await client.send_packet(mocker.sentinel.packet)
            return b""

        mock_stream_socket_adapter.recv = mocker.MagicMock(side_effect=recv_side_effect)

        # Act
        with pytest.raises(ConnectionAbortedError):
            _ = await client.recv_packet()

        # Assert
        mock_stream_protocol.generate_chunks.assert_called_with(mocker.sentinel.packet)
        mock_stream_socket_adapter.send_all_from_iterable.assert_called()
        mock_stream_socket_adapter.send_all.assert_called_with(b"packet\n")
