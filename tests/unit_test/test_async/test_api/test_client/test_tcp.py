from __future__ import annotations

import contextlib
import errno
import os
import ssl
from collections.abc import AsyncIterator
from socket import AF_INET, AF_INET6, IPPROTO_TCP, SO_ERROR, SO_KEEPALIVE, SOL_SOCKET, TCP_NODELAY
from typing import TYPE_CHECKING, Any

from easynetwork.clients.async_tcp import AsyncTCPNetworkClient
from easynetwork.exceptions import ClientClosedError, IncrementalDeserializeError, StreamProtocolParseError
from easynetwork.lowlevel.api_async.endpoints.stream import AsyncStreamEndpoint
from easynetwork.lowlevel.api_async.transports.tls import AsyncTLSStreamTransport
from easynetwork.lowlevel.constants import CLOSED_SOCKET_ERRNOS, DEFAULT_STREAM_BUFSIZE
from easynetwork.lowlevel.socket import IPv4SocketAddress, IPv6SocketAddress, SocketProxy, _get_socket_extra, _get_tls_extra

import pytest
import pytest_asyncio

from ...._utils import AsyncDummyLock, unsupported_families
from ....base import INET_FAMILIES
from ...mock_tools import make_transport_mock
from .base import BaseTestClient

if TYPE_CHECKING:
    from unittest.mock import AsyncMock, MagicMock

    from pytest_mock import MockerFixture

    from .....pytest_plugins.async_finalizer import AsyncFinalizer


@pytest.mark.asyncio
class TestAsyncTCPNetworkClient(BaseTestClient):
    @pytest.fixture(params=["NO_SSL", "USE_SSL"])
    @staticmethod
    def use_ssl(request: pytest.FixtureRequest) -> bool:
        match request.param:
            case "NO_SSL":
                return False
            case "USE_SSL":
                return True
            case _:
                pytest.fail(f"Invalid use_ssl parameter: {request.param}")

    @pytest.fixture(scope="class", params=INET_FAMILIES)
    @staticmethod
    def socket_family(request: pytest.FixtureRequest) -> int:
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
    @classmethod
    def local_address(
        cls,
        mock_tcp_socket: MagicMock,
        socket_family: int,
        global_local_address: tuple[str, int],
    ) -> tuple[str, int]:
        if socket_family in (AF_INET, AF_INET6):
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
        if socket_family in (AF_INET, AF_INET6):
            cls.set_remote_address_to_socket_mock(
                mock_tcp_socket,
                socket_family,
                global_remote_address,
            )
        return global_remote_address

    @pytest.fixture
    @staticmethod
    def mock_stream_endpoint(mocker: MockerFixture, mock_backend: MagicMock) -> MagicMock:
        mock_stream_endpoint = make_transport_mock(mocker=mocker, spec=AsyncStreamEndpoint, backend=mock_backend)
        mock_stream_endpoint.recv_packet.return_value = mocker.sentinel.packet
        mock_stream_endpoint.send_packet.return_value = None
        mock_stream_endpoint.send_eof.return_value = None
        return mock_stream_endpoint

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_stream_endpoint_cls(mocker: MockerFixture, mock_stream_endpoint: MagicMock) -> MagicMock:
        from easynetwork.lowlevel._utils import Flag

        was_called = Flag()

        def mock_endpoint_side_effect(transport: MagicMock, *args: Any, **kwargs: Any) -> MagicMock:
            if was_called.is_set():
                raise RuntimeError("Must be called once.")
            was_called.set()
            mock_stream_endpoint.extra_attributes = transport.extra_attributes
            return mock_stream_endpoint

        return mocker.patch(
            f"{AsyncTCPNetworkClient.__module__}.AsyncStreamEndpoint",
            side_effect=mock_endpoint_side_effect,
        )

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_ssl_create_default_context(mock_ssl_context: MagicMock, mocker: MockerFixture) -> MagicMock:
        return mocker.patch("ssl.create_default_context", autospec=True, side_effect=[mock_ssl_context])

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_tls_wrap_transport(mock_ssl_object: MagicMock, mocker: MockerFixture) -> AsyncMock:
        def wrap_side_effect(
            transport: MagicMock,
            ssl_context: MagicMock,
            *args: Any,
            **kwargs: Any,
        ) -> MagicMock:
            mock_ssl_object.context = ssl_context
            mock_ssl_object.getpeercert.return_value = mocker.sentinel.peercert
            mock_ssl_object.cipher.return_value = mocker.sentinel.cipher
            mock_ssl_object.compression.return_value = mocker.sentinel.compression
            mock_ssl_object.version.return_value = mocker.sentinel.tls_version
            transport.extra_attributes = {
                **transport.extra_attributes,
                **_get_tls_extra(mock_ssl_object, kwargs.get("standard_compatible", True)),
            }
            return transport

        return mocker.patch.object(AsyncTLSStreamTransport, "wrap", autospec=True, side_effect=wrap_side_effect)

    @pytest.fixture(autouse=True)
    @staticmethod
    def set_default_socket_mock_configuration(
        mock_tcp_socket: MagicMock,
        mock_backend: MagicMock,
        socket_family: int,
        mock_stream_transport: MagicMock,
    ) -> None:
        mock_tcp_socket.family = socket_family
        mock_tcp_socket.getsockopt.return_value = 0  # Needed for tests dealing with send_packet()

        mock_backend.create_tcp_connection.return_value = mock_stream_transport
        mock_backend.wrap_stream_socket.return_value = mock_stream_transport

        mock_stream_transport.backend.return_value = mock_backend
        mock_stream_transport.extra_attributes = _get_socket_extra(mock_tcp_socket, wrap_in_proxy=False)

    @pytest_asyncio.fixture
    @staticmethod
    async def client_not_connected(
        use_ssl: bool,
        mock_backend: MagicMock,
        mock_tcp_socket: MagicMock,
        mock_stream_protocol: MagicMock,
    ) -> AsyncIterator[AsyncTCPNetworkClient[Any, Any]]:
        client: AsyncTCPNetworkClient[Any, Any] = AsyncTCPNetworkClient(
            mock_tcp_socket,
            mock_stream_protocol,
            mock_backend,
            ssl=use_ssl,
            server_hostname="server_hostname" if use_ssl else None,
        )
        async with contextlib.aclosing(client):
            assert not client.is_connected()
            yield client

    @pytest_asyncio.fixture
    @staticmethod
    async def client_connected(
        use_ssl: bool,
        mock_backend: MagicMock,
        mock_tcp_socket: MagicMock,
        mock_stream_protocol: MagicMock,
    ) -> AsyncIterator[AsyncTCPNetworkClient[Any, Any]]:
        client: AsyncTCPNetworkClient[Any, Any] = AsyncTCPNetworkClient(
            mock_tcp_socket,
            mock_stream_protocol,
            mock_backend,
            ssl=use_ssl,
            server_hostname="server_hostname" if use_ssl else None,
        )
        async with contextlib.aclosing(client):
            await client.wait_connected()
            assert client.is_connected()
            yield client

    @pytest_asyncio.fixture(params=[False, True], ids=lambda boolean: f"client_connected=={boolean}")
    @staticmethod
    async def client_connected_or_not(
        request: pytest.FixtureRequest,
        use_ssl: bool,
        mock_backend: MagicMock,
        mock_tcp_socket: MagicMock,
        mock_stream_protocol: MagicMock,
    ) -> AsyncIterator[AsyncTCPNetworkClient[Any, Any]]:
        assert request.param in (True, False)
        client: AsyncTCPNetworkClient[Any, Any] = AsyncTCPNetworkClient(
            mock_tcp_socket,
            mock_stream_protocol,
            mock_backend,
            ssl=use_ssl,
            server_hostname="server_hostname" if use_ssl else None,
        )
        async with contextlib.aclosing(client):
            if request.param:
                await client.wait_connected()
                assert client.is_connected()
            else:
                assert not client.is_connected()
            yield client

    @pytest.mark.parametrize("max_recv_size", [None, 123456789], ids=lambda p: f"max_recv_size=={p}")
    async def test____dunder_init____connect_to_remote(
        self,
        max_recv_size: int | None,
        async_finalizer: AsyncFinalizer,
        local_address: tuple[str, int],
        remote_address: tuple[str, int],
        mock_tcp_socket: MagicMock,
        mock_backend: MagicMock,
        mock_stream_endpoint_cls: MagicMock,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_tls_wrap_transport: AsyncMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        expected_max_recv_size: int = DEFAULT_STREAM_BUFSIZE if max_recv_size is None else max_recv_size

        # Act
        client: AsyncTCPNetworkClient[Any, Any] = AsyncTCPNetworkClient(
            remote_address,
            protocol=mock_stream_protocol,
            backend=mock_backend,
            local_address=local_address,
            happy_eyeballs_delay=mocker.sentinel.happy_eyeballs_delay,
            max_recv_size=max_recv_size,
        )
        async_finalizer.add_finalizer(client.aclose)
        await client.wait_connected()

        # Assert
        mock_backend.create_tcp_connection.assert_awaited_once_with(
            *remote_address,
            local_address=local_address,
            happy_eyeballs_delay=mocker.sentinel.happy_eyeballs_delay,
        )
        mock_tls_wrap_transport.assert_not_awaited()
        mock_stream_endpoint_cls.assert_called_once_with(
            mock_stream_transport,
            mock_stream_protocol,
            max_recv_size=expected_max_recv_size,
        )
        assert mock_tcp_socket.mock_calls == [
            mocker.call.setsockopt(IPPROTO_TCP, TCP_NODELAY, True),
            mocker.call.setsockopt(SOL_SOCKET, SO_KEEPALIVE, True),
        ]
        assert isinstance(client.socket, SocketProxy)

    @pytest.mark.parametrize("max_recv_size", [None, 123456789], ids=lambda p: f"max_recv_size=={p}")
    async def test____dunder_init____use_given_socket(
        self,
        max_recv_size: int | None,
        async_finalizer: AsyncFinalizer,
        mock_tcp_socket: MagicMock,
        mock_backend: MagicMock,
        mock_stream_endpoint_cls: MagicMock,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_tls_wrap_transport: AsyncMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        expected_max_recv_size: int = DEFAULT_STREAM_BUFSIZE if max_recv_size is None else max_recv_size

        # Act
        client: AsyncTCPNetworkClient[Any, Any] = AsyncTCPNetworkClient(
            mock_tcp_socket,
            protocol=mock_stream_protocol,
            backend=mock_backend,
            max_recv_size=max_recv_size,
        )
        async_finalizer.add_finalizer(client.aclose)
        await client.wait_connected()

        # Assert
        mock_backend.wrap_stream_socket.assert_awaited_once_with(mock_tcp_socket)
        mock_tls_wrap_transport.assert_not_awaited()
        mock_stream_endpoint_cls.assert_called_once_with(
            mock_stream_transport,
            mock_stream_protocol,
            max_recv_size=expected_max_recv_size,
        )
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
        mocker: MockerFixture,
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
        assert mock_tcp_socket.mock_calls == [
            mocker.call.getpeername(),
            mocker.call.close(),
        ]

    @pytest.mark.parametrize("socket_family", list(unsupported_families(INET_FAMILIES)), indirect=True)
    async def test____dunder_init____use_given_socket____invalid_socket_family(
        self,
        use_ssl: bool,
        mock_backend: MagicMock,
        mock_tcp_socket: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        server_hostname: str | None = None
        if use_ssl:
            server_hostname = "test.example.com"

        # Act & Assert
        with pytest.raises(ValueError, match=r"^Only these families are supported: .+$"):
            _ = AsyncTCPNetworkClient(
                mock_tcp_socket,
                protocol=mock_stream_protocol,
                backend=mock_backend,
                ssl=use_ssl,
                server_hostname=server_hostname,
            )

        assert mock_tcp_socket.mock_calls == [
            mocker.call.close(),
        ]

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
        local_address: tuple[str, int],
        remote_address: tuple[str, int],
        mock_tcp_socket: MagicMock,
        mock_backend: MagicMock,
        mock_stream_endpoint_cls: MagicMock,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_ssl_context: MagicMock,
        mock_ssl_create_default_context: MagicMock,
        mock_tls_wrap_transport: AsyncMock,
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
                local_address=local_address,
                happy_eyeballs_delay=mocker.sentinel.happy_eyeballs_delay,
            )
        async_finalizer.add_finalizer(client.aclose)
        await client.wait_connected()

        # Assert
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
                local_address=local_address,
                happy_eyeballs_delay=mocker.sentinel.happy_eyeballs_delay,
            )
            assert mock_tcp_socket.mock_calls == [
                mocker.call.setsockopt(IPPROTO_TCP, TCP_NODELAY, True),
                mocker.call.setsockopt(SOL_SOCKET, SO_KEEPALIVE, True),
            ]
        mock_tls_wrap_transport.assert_awaited_once_with(
            mock_stream_transport,
            mock_ssl_context,
            server_side=False,
            server_hostname="server_hostname",
            handshake_timeout=mocker.sentinel.ssl_handshake_timeout,
            shutdown_timeout=mocker.sentinel.ssl_shutdown_timeout,
            standard_compatible=mocker.sentinel.ssl_standard_compatible,
        )
        mock_stream_endpoint_cls.assert_called_once_with(
            mock_stream_transport,
            mock_stream_protocol,
            max_recv_size=DEFAULT_STREAM_BUFSIZE,
        )
        assert isinstance(client.socket, SocketProxy)

    @pytest.mark.parametrize("use_socket", [False, True], ids=lambda p: f"use_socket=={p}")
    async def test____dunder_init____ssl____default_values(
        self,
        async_finalizer: AsyncFinalizer,
        use_socket: bool,
        local_address: tuple[str, int],
        remote_address: tuple[str, int],
        mock_backend: MagicMock,
        mock_tcp_socket: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_ssl_context: MagicMock,
        mock_tls_wrap_transport: AsyncMock,
        mock_stream_transport: MagicMock,
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
                local_address=local_address,
                happy_eyeballs_delay=mocker.sentinel.happy_eyeballs_delay,
            )
        async_finalizer.add_finalizer(client.aclose)
        await client.wait_connected()

        # Assert
        mock_tls_wrap_transport.assert_awaited_once_with(
            mock_stream_transport,
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

    async def test____dunder_init____ssl____server_hostname____use_remote_host_by_default(
        self,
        async_finalizer: AsyncFinalizer,
        local_address: tuple[str, int],
        remote_address: tuple[str, int],
        mock_backend: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_ssl_context: MagicMock,
        mock_tls_wrap_transport: AsyncMock,
        mock_stream_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        remote_host, _ = remote_address

        # Act
        client: AsyncTCPNetworkClient[Any, Any] = AsyncTCPNetworkClient(
            remote_address,
            protocol=mock_stream_protocol,
            backend=mock_backend,
            ssl=mock_ssl_context,
            server_hostname=None,
            ssl_handshake_timeout=mocker.sentinel.ssl_handshake_timeout,
            ssl_shutdown_timeout=mocker.sentinel.ssl_shutdown_timeout,
            ssl_standard_compatible=mocker.sentinel.ssl_standard_compatible,
            local_address=local_address,
            happy_eyeballs_delay=mocker.sentinel.happy_eyeballs_delay,
        )
        async_finalizer.add_finalizer(client.aclose)
        await client.wait_connected()

        # Assert
        mock_tls_wrap_transport.assert_awaited_once_with(
            mock_stream_transport,
            mock_ssl_context,
            server_side=False,
            server_hostname=remote_host,
            handshake_timeout=mocker.sentinel.ssl_handshake_timeout,
            shutdown_timeout=mocker.sentinel.ssl_shutdown_timeout,
            standard_compatible=mocker.sentinel.ssl_standard_compatible,
        )

    @pytest.mark.parametrize("use_socket", [False, True], ids=lambda p: f"use_socket=={p}")
    async def test____dunder_init____ssl____server_hostname____do_not_disable_hostname_check_for_external_context(
        self,
        async_finalizer: AsyncFinalizer,
        use_socket: bool,
        local_address: tuple[str, int],
        remote_address: tuple[str, int],
        mock_backend: MagicMock,
        mock_tcp_socket: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_ssl_context: MagicMock,
        mock_tls_wrap_transport: AsyncMock,
        mock_stream_transport: MagicMock,
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
                local_address=local_address,
                happy_eyeballs_delay=mocker.sentinel.happy_eyeballs_delay,
            )
        async_finalizer.add_finalizer(client.aclose)
        await client.wait_connected()

        # Assert
        mock_tls_wrap_transport.assert_awaited_once_with(
            mock_stream_transport,
            mock_ssl_context,
            server_side=False,
            server_hostname=None,
            handshake_timeout=mocker.sentinel.ssl_handshake_timeout,
            shutdown_timeout=mocker.sentinel.ssl_shutdown_timeout,
            standard_compatible=mocker.sentinel.ssl_standard_compatible,
        )
        assert mock_ssl_context.check_hostname is True

    @pytest.mark.parametrize("use_socket", [False, True], ids=lambda p: f"use_socket=={p}")
    async def test____dunder_init____ssl____server_hostname____no_host_to_use(
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
        remote_address = ("", remote_address[1])
        mock_backend.create_tcp_connection.side_effect = AssertionError
        mock_backend.wrap_stream_socket.side_effect = AssertionError

        # Act & Assert
        with pytest.raises(ValueError, match=r"^You must set server_hostname when using ssl without a host$"):
            if use_socket:
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
            else:
                _ = AsyncTCPNetworkClient(
                    remote_address,
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
        local_address: tuple[str, int],
        remote_address: tuple[str, int],
        mock_backend: MagicMock,
        mock_tcp_socket: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_ssl_context: MagicMock,
        mock_ssl_create_default_context: MagicMock,
        mock_tls_wrap_transport: AsyncMock,
        mock_stream_transport: MagicMock,
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
                local_address=local_address,
                happy_eyeballs_delay=mocker.sentinel.happy_eyeballs_delay,
            )
        async_finalizer.add_finalizer(client.aclose)
        await client.wait_connected()

        # Assert
        mock_ssl_create_default_context.assert_called_once_with()
        mock_tls_wrap_transport.assert_awaited_once_with(
            mock_stream_transport,
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
        local_address: tuple[str, int],
        remote_address: tuple[str, int],
        mock_backend: MagicMock,
        mock_tcp_socket: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_ssl_context: MagicMock,
        mock_ssl_create_default_context: MagicMock,
        mock_tls_wrap_transport: AsyncMock,
        mock_stream_transport: MagicMock,
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
                local_address=local_address,
                happy_eyeballs_delay=mocker.sentinel.happy_eyeballs_delay,
            )
        async_finalizer.add_finalizer(client.aclose)
        await client.wait_connected()

        # Assert
        mock_ssl_create_default_context.assert_called_once_with()
        mock_tls_wrap_transport.assert_awaited_once_with(
            mock_stream_transport,
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
        mock_stream_endpoint: MagicMock,
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

        mock_stream_endpoint.aclose.assert_not_called()

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
        mock_stream_endpoint: MagicMock,
    ) -> None:
        # Arrange
        assert not client_connected.is_closing()

        # Act
        await client_connected.aclose()

        # Assert
        assert client_connected.is_closing()
        mock_stream_endpoint.aclose.assert_awaited_once_with()

    async def test____aclose____connection_not_performed_yet(
        self,
        client_not_connected: AsyncTCPNetworkClient[Any, Any],
        mock_stream_endpoint: MagicMock,
    ) -> None:
        # Arrange
        assert not client_not_connected.is_closing()

        # Act
        await client_not_connected.aclose()

        # Assert
        assert client_not_connected.is_closing()
        mock_stream_endpoint.aclose.assert_not_awaited()

    async def test____aclose____already_closed(
        self,
        client_connected: AsyncTCPNetworkClient[Any, Any],
        mock_stream_endpoint: MagicMock,
    ) -> None:
        # Arrange
        await client_connected.aclose()
        assert client_connected.is_closing()

        # Act
        await client_connected.aclose()

        # Assert
        assert mock_stream_endpoint.aclose.await_count == 2

    async def test____aclose____cancelled(
        self,
        client_connected: AsyncTCPNetworkClient[Any, Any],
        mock_stream_endpoint: MagicMock,
        fake_cancellation_cls: type[BaseException],
    ) -> None:
        # Arrange
        old_side_effect = mock_stream_endpoint.aclose.side_effect
        mock_stream_endpoint.aclose.side_effect = fake_cancellation_cls

        # Act
        try:
            with pytest.raises(fake_cancellation_cls):
                await client_connected.aclose()
        finally:
            mock_stream_endpoint.aclose.side_effect = old_side_effect

        # Assert
        mock_stream_endpoint.aclose.assert_awaited_once_with()

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
        mock_tcp_socket.getsockname.reset_mock()

        # Act
        with pytest.raises(OSError) as exc_info:
            client_not_connected.get_local_address()

        # Assert
        assert exc_info.value.errno == errno.ENOTCONN
        mock_tcp_socket.getsockname.assert_not_called()

    async def test____get_local_address____client_closed(
        self,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange
        await client_connected_or_not.aclose()
        assert client_connected_or_not.is_closing()
        mock_tcp_socket.getsockname.reset_mock()

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
        mock_tcp_socket.getpeername.reset_mock()

        # Act
        with pytest.raises(OSError) as exc_info:
            client_not_connected.get_remote_address()

        # Assert
        assert exc_info.value.errno == errno.ENOTCONN
        mock_tcp_socket.getpeername.assert_not_called()

    async def test____get_remote_address____client_closed(
        self,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange
        await client_connected_or_not.aclose()
        assert client_connected_or_not.is_closing()
        mock_tcp_socket.getpeername.reset_mock()

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

    async def test____socket_property____cached_attribute(
        self,
        client_connected: AsyncTCPNetworkClient[Any, Any],
    ) -> None:
        # Arrange

        # Act & Assert
        assert client_connected.socket is client_connected.socket

    async def test____socket_property____AttributeError(
        self,
        client_not_connected: AsyncTCPNetworkClient[Any, Any],
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(AttributeError):
            _ = client_not_connected.socket

    async def test____send_packet____send_bytes_to_socket(
        self,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_tcp_socket: MagicMock,
        mock_stream_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        await client_connected_or_not.send_packet(mocker.sentinel.packet)

        # Assert
        mock_stream_endpoint.send_packet.assert_awaited_once_with(mocker.sentinel.packet)
        mock_tcp_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_ERROR)

    async def test____send_packet____raise_error_saved_in_SO_ERROR_option(
        self,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_tcp_socket: MagicMock,
        mock_stream_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        mock_tcp_socket.getsockopt.return_value = errno.EBUSY

        # Act
        with pytest.raises(OSError) as exc_info:
            await client_connected_or_not.send_packet(mocker.sentinel.packet)

        # Assert
        assert exc_info.value.errno == errno.EBUSY
        mock_stream_endpoint.send_packet.assert_awaited_once_with(mocker.sentinel.packet)
        mock_tcp_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_ERROR)

    async def test____send_packet____closed_client_error(
        self,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_tcp_socket: MagicMock,
        mock_stream_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        await client_connected_or_not.aclose()
        assert client_connected_or_not.is_closing()

        # Act
        with pytest.raises(ClientClosedError):
            await client_connected_or_not.send_packet(mocker.sentinel.packet)

        # Assert
        mock_stream_endpoint.send_packet.assert_not_called()
        mock_tcp_socket.getsockopt.assert_not_called()

    async def test____send_packet____convert_connection_errors(
        self,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_tcp_socket: MagicMock,
        mock_stream_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_endpoint.send_packet.side_effect = ConnectionError

        # Act
        with pytest.raises(ConnectionAbortedError):
            await client_connected_or_not.send_packet(mocker.sentinel.packet)

        # Assert
        mock_stream_endpoint.send_packet.assert_awaited_once_with(mocker.sentinel.packet)
        mock_stream_endpoint.aclose.assert_not_called()
        mock_tcp_socket.getsockopt.assert_not_called()

    @pytest.mark.parametrize("closed_socket_errno", sorted(CLOSED_SOCKET_ERRNOS), ids=errno.errorcode.__getitem__)
    async def test____send_packet____convert_closed_socket_error(
        self,
        closed_socket_errno: int,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_tcp_socket: MagicMock,
        mock_stream_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_endpoint.send_packet.side_effect = OSError(closed_socket_errno, os.strerror(closed_socket_errno))

        # Act
        with pytest.raises(OSError) as exc_info:
            await client_connected_or_not.send_packet(mocker.sentinel.packet)

        # Assert
        assert exc_info.value.errno == closed_socket_errno
        assert exc_info.value.__notes__ == ["The socket file descriptor was closed unexpectedly."]
        assert not client_connected_or_not.is_closing()
        mock_stream_endpoint.send_packet.assert_awaited_once_with(mocker.sentinel.packet)
        mock_stream_endpoint.aclose.assert_not_awaited()
        mock_tcp_socket.getsockopt.assert_not_called()

    @pytest.mark.parametrize("use_ssl", ["USE_SSL"], indirect=True)
    async def test____send_packet____ssl____unrelated_ssl_errors(
        self,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_tcp_socket: MagicMock,
        mock_stream_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_endpoint.send_packet.side_effect = ssl.SSLError(
            ssl.SSLErrorNumber.SSL_ERROR_INVALID_ERROR_CODE,
            "SOMETHING",
        )

        # Act
        with pytest.raises(ssl.SSLError) as exc_info:
            await client_connected_or_not.send_packet(mocker.sentinel.packet)

        # Assert
        assert exc_info.value.errno == ssl.SSLErrorNumber.SSL_ERROR_INVALID_ERROR_CODE
        assert exc_info.value.strerror == "SOMETHING"
        mock_stream_endpoint.send_packet.assert_awaited_once_with(mocker.sentinel.packet)
        mock_stream_endpoint.aclose.assert_not_called()
        mock_tcp_socket.getsockopt.assert_not_called()

    @pytest.mark.parametrize("use_ssl", ["USE_SSL"], indirect=True)
    async def test____send_packet____ssl____ragged_eof_error(
        self,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_tcp_socket: MagicMock,
        mock_stream_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_endpoint.send_packet.side_effect = ssl.SSLEOFError()

        # Act
        with pytest.raises(ConnectionAbortedError):
            await client_connected_or_not.send_packet(mocker.sentinel.packet)

        # Assert
        mock_stream_endpoint.send_packet.assert_awaited_once_with(mocker.sentinel.packet)
        mock_stream_endpoint.aclose.assert_not_called()
        mock_tcp_socket.getsockopt.assert_not_called()

    @pytest.mark.parametrize("use_ssl", ["NO_SSL"], indirect=True)
    async def test____send_eof____socket_send_eof(
        self,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_stream_endpoint: MagicMock,
    ) -> None:
        # Arrange

        # Act
        await client_connected_or_not.send_eof()

        # Assert
        mock_stream_endpoint.send_eof.assert_awaited_once_with()
        mock_stream_endpoint.aclose.assert_not_called()

    @pytest.mark.parametrize("use_ssl", ["NO_SSL"], indirect=True)
    async def test____send_eof____closed_client(
        self,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_stream_endpoint: MagicMock,
    ) -> None:
        # Arrange
        await client_connected_or_not.aclose()

        # Act
        await client_connected_or_not.send_eof()

        # Assert
        mock_stream_endpoint.send_eof.assert_not_awaited()

    @pytest.mark.parametrize("closed_socket_errno", sorted(CLOSED_SOCKET_ERRNOS), ids=errno.errorcode.__getitem__)
    @pytest.mark.parametrize("use_ssl", ["NO_SSL"], indirect=True)
    async def test____send_eof____closed_socket_error(
        self,
        closed_socket_errno: int,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_stream_endpoint: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_endpoint.send_eof.side_effect = OSError(closed_socket_errno, os.strerror(closed_socket_errno))

        # Act
        with pytest.raises(OSError) as exc_info:
            await client_connected_or_not.send_eof()

        # Assert
        assert exc_info.value.errno == closed_socket_errno
        assert exc_info.value.__notes__ == ["The socket file descriptor was closed unexpectedly."]
        assert not client_connected_or_not.is_closing()
        mock_stream_endpoint.send_eof.assert_awaited_once_with()
        mock_stream_endpoint.aclose.assert_not_awaited()

    async def test____recv_packet____receive_bytes_from_socket(
        self,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_stream_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_endpoint.recv_packet.side_effect = [mocker.sentinel.packet]

        # Act
        packet: Any = await client_connected_or_not.recv_packet()

        # Assert
        mock_stream_endpoint.recv_packet.assert_awaited_once_with()
        assert packet is mocker.sentinel.packet

    async def test____recv_packet____protocol_parse_error(
        self,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_stream_endpoint: MagicMock,
    ) -> None:
        # Arrange
        expected_error = StreamProtocolParseError(b"", IncrementalDeserializeError("Sorry", b""))
        mock_stream_endpoint.recv_packet.side_effect = [expected_error]

        # Act
        with pytest.raises(StreamProtocolParseError) as exc_info:
            _ = await client_connected_or_not.recv_packet()

        # Assert
        assert exc_info.value is expected_error

    async def test____recv_packet____closed_client_error(
        self,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_stream_endpoint: MagicMock,
    ) -> None:
        # Arrange
        await client_connected_or_not.aclose()
        assert client_connected_or_not.is_closing()

        # Act
        with pytest.raises(ClientClosedError):
            _ = await client_connected_or_not.recv_packet()

        # Assert
        mock_stream_endpoint.recv_packet.assert_not_awaited()

    async def test____recv_packet____convert_connection_errors(
        self,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_stream_endpoint: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_endpoint.recv_packet.side_effect = ConnectionError

        # Act
        with pytest.raises(ConnectionAbortedError):
            _ = await client_connected_or_not.recv_packet()

        # Assert
        mock_stream_endpoint.recv_packet.assert_awaited_once_with()

    @pytest.mark.parametrize("use_ssl", ["USE_SSL"], indirect=True)
    async def test____recv_packet____ssl____unrelated_ssl_error(
        self,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_stream_endpoint: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_endpoint.recv_packet.side_effect = ssl.SSLError(
            ssl.SSLErrorNumber.SSL_ERROR_INVALID_ERROR_CODE,
            "SOMETHING",
        )

        # Act
        with pytest.raises(ssl.SSLError) as exc_info:
            _ = await client_connected_or_not.recv_packet()

        # Assert
        assert exc_info.value.errno == ssl.SSLErrorNumber.SSL_ERROR_INVALID_ERROR_CODE
        assert exc_info.value.strerror == "SOMETHING"
        mock_stream_endpoint.recv_packet.assert_awaited_once_with()

    @pytest.mark.parametrize("use_ssl", ["USE_SSL"], indirect=True)
    async def test____recv_packet____ssl____ragged_eof_error(
        self,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_stream_endpoint: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_endpoint.recv_packet.side_effect = ssl.SSLEOFError()

        # Act
        with pytest.raises(ConnectionAbortedError):
            _ = await client_connected_or_not.recv_packet()

        # Assert
        mock_stream_endpoint.recv_packet.assert_awaited_once_with()

    @pytest.mark.parametrize("closed_socket_errno", sorted(CLOSED_SOCKET_ERRNOS), ids=errno.errorcode.__getitem__)
    async def test____recv_packet____convert_closed_socket_errors(
        self,
        closed_socket_errno: int,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_stream_endpoint: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_endpoint.recv_packet.side_effect = OSError(closed_socket_errno, os.strerror(closed_socket_errno))

        # Act
        with pytest.raises(OSError) as exc_info:
            _ = await client_connected_or_not.recv_packet()

        # Assert
        assert exc_info.value.errno == closed_socket_errno
        assert exc_info.value.__notes__ == ["The socket file descriptor was closed unexpectedly."]
        assert not client_connected_or_not.is_closing()
        mock_stream_endpoint.recv_packet.assert_awaited_once_with()
        mock_stream_endpoint.aclose.assert_not_awaited()

    async def test____special_case____separate_send_and_receive_locks(
        self,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_stream_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        async def recv_side_effect() -> bytes:
            await client_connected_or_not.send_packet(mocker.sentinel.packet)
            raise ConnectionAbortedError

        mock_stream_endpoint.recv_packet.side_effect = recv_side_effect

        # Act
        with pytest.raises(ConnectionAbortedError):
            _ = await client_connected_or_not.recv_packet()

        # Assert
        mock_stream_endpoint.send_packet.assert_awaited_once_with(mocker.sentinel.packet)

    @pytest.mark.parametrize("closed_socket_errno", sorted(CLOSED_SOCKET_ERRNOS), ids=errno.errorcode.__getitem__)
    async def test____special_case____close_during_recv_call(
        self,
        closed_socket_errno: int,
        client_connected_or_not: AsyncTCPNetworkClient[Any, Any],
        mock_stream_endpoint: MagicMock,
    ) -> None:
        # Arrange
        async def recv_side_effect() -> bytes:
            await client_connected_or_not.aclose()
            raise OSError(closed_socket_errno, os.strerror(closed_socket_errno))

        mock_stream_endpoint.recv_packet.side_effect = recv_side_effect

        # Act & Assert
        with pytest.raises(ClientClosedError):
            _ = await client_connected_or_not.recv_packet()

    async def test____special_case____close_cancelled_during_lock_acquisition(
        self,
        client_connected: AsyncTCPNetworkClient[Any, Any],
        mock_stream_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        ## We simulate another task which takes the lock and aclose() has been cancelled.
        CancelledError = client_connected.backend().get_cancelled_exc_class()
        mock_lock_acquire = mocker.patch.object(AsyncDummyLock, "acquire", side_effect=CancelledError)

        # Act
        with pytest.raises(CancelledError):
            await client_connected.aclose()
        mocker.stop(mock_lock_acquire)

        # Assert
        mock_stream_endpoint.aclose.assert_awaited_once_with()

    async def test____special_case____close_cancelled_during_lock_acquisition____endpoint_is_already_closing(
        self,
        client_connected: AsyncTCPNetworkClient[Any, Any],
        mock_stream_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        await mock_stream_endpoint.aclose()
        assert mock_stream_endpoint.is_closing()
        mock_stream_endpoint.reset_mock()
        ## We simulate another task which takes the lock and aclose() has been cancelled.
        CancelledError = client_connected.backend().get_cancelled_exc_class()
        mock_lock_acquire = mocker.patch.object(AsyncDummyLock, "acquire", side_effect=CancelledError)

        # Act
        with pytest.raises(CancelledError):
            await client_connected.aclose()
        mocker.stop(mock_lock_acquire)

        # Assert
        mock_stream_endpoint.aclose.assert_not_awaited()
