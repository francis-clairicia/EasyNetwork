from __future__ import annotations

import errno
import os
import ssl
from collections.abc import Iterator
from socket import AF_INET, AF_INET6, IPPROTO_TCP, SO_ERROR, SO_KEEPALIVE, SOL_SOCKET, TCP_NODELAY
from ssl import SSLEOFError, SSLError, SSLErrorNumber
from typing import TYPE_CHECKING, Any

from easynetwork.clients.tcp import TCPNetworkClient
from easynetwork.exceptions import ClientClosedError, IncrementalDeserializeError, StreamProtocolParseError
from easynetwork.lowlevel.api_sync.endpoints.stream import StreamEndpoint
from easynetwork.lowlevel.api_sync.transports.socket import SocketStreamTransport, SSLStreamTransport
from easynetwork.lowlevel.constants import CLOSED_SOCKET_ERRNOS, DEFAULT_STREAM_BUFSIZE
from easynetwork.lowlevel.socket import IPv4SocketAddress, IPv6SocketAddress, SocketProxy, _get_socket_extra, _get_tls_extra

import pytest

from ...._utils import unsupported_families
from ....base import INET_FAMILIES
from ...mock_tools import make_transport_mock
from .base import BaseTestClient

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class TestTCPNetworkClient(BaseTestClient):
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
        mock_ssl_socket: MagicMock,
        socket_family: int,
        global_local_address: tuple[str, int],
    ) -> tuple[str, int]:
        if socket_family in (AF_INET, AF_INET6):
            cls.set_local_address_to_socket_mock(mock_tcp_socket, socket_family, global_local_address)
            cls.set_local_address_to_socket_mock(mock_ssl_socket, socket_family, global_local_address)
        return global_local_address

    @pytest.fixture(autouse=True)
    @classmethod
    def remote_address(
        cls,
        mock_tcp_socket: MagicMock,
        mock_ssl_socket: MagicMock,
        socket_family: int,
        global_remote_address: tuple[str, int],
    ) -> tuple[str, int]:
        if socket_family in (AF_INET, AF_INET6):
            cls.set_remote_address_to_socket_mock(mock_tcp_socket, socket_family, global_remote_address)
            cls.set_remote_address_to_socket_mock(mock_ssl_socket, socket_family, global_remote_address)
        return global_remote_address

    @pytest.fixture
    @staticmethod
    def mock_stream_endpoint(mocker: MockerFixture) -> MagicMock:
        mock_stream_endpoint = make_transport_mock(mocker=mocker, spec=StreamEndpoint)
        mock_stream_endpoint.recv_packet.return_value = mocker.sentinel.packet
        mock_stream_endpoint.send_packet.return_value = None
        mock_stream_endpoint.send_eof.return_value = None
        return mock_stream_endpoint

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_stream_endpoint_cls(mocker: MockerFixture, mock_stream_endpoint: MagicMock) -> MagicMock:
        from easynetwork.lowlevel._stream import _check_any_protocol
        from easynetwork.lowlevel._utils import Flag

        was_called = Flag()

        def mock_endpoint_side_effect(transport: MagicMock, protocol: MagicMock, *args: Any, **kwargs: Any) -> MagicMock:
            if was_called.is_set():
                raise RuntimeError("Must be called once.")
            was_called.set()
            _check_any_protocol(protocol)
            mock_stream_endpoint.extra_attributes = transport.extra_attributes
            return mock_stream_endpoint

        return mocker.patch(
            f"{TCPNetworkClient.__module__}.StreamEndpoint",
            side_effect=mock_endpoint_side_effect,
        )

    @pytest.fixture
    @staticmethod
    def mock_socket_stream_transport(mocker: MockerFixture) -> MagicMock:
        return make_transport_mock(mocker=mocker, spec=SocketStreamTransport)

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_socket_stream_transport_cls(mocker: MockerFixture, mock_socket_stream_transport: MagicMock) -> MagicMock:
        from easynetwork.lowlevel._utils import Flag

        was_called = Flag()

        def mock_transport_side_effect(sock: MagicMock, *args: Any, **kwargs: Any) -> MagicMock:
            if was_called.is_set():
                raise RuntimeError("Must be called once.")
            was_called.set()
            sock.setblocking(False)
            mock_socket_stream_transport.extra_attributes = _get_socket_extra(sock, wrap_in_proxy=False)
            return mock_socket_stream_transport

        return mocker.patch(
            f"{SocketStreamTransport.__module__}.SocketStreamTransport",
            side_effect=mock_transport_side_effect,
        )

    @pytest.fixture
    @staticmethod
    def mock_ssl_stream_transport(mocker: MockerFixture) -> MagicMock:
        return make_transport_mock(mocker=mocker, spec=SSLStreamTransport)

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_ssl_stream_transport_cls(
        mocker: MockerFixture,
        mock_ssl_socket: MagicMock,
        mock_ssl_stream_transport: MagicMock,
    ) -> MagicMock:
        from easynetwork.lowlevel._utils import Flag

        was_called = Flag()

        def mock_transport_side_effect(sock: MagicMock, ssl_context: MagicMock, *args: Any, **kwargs: Any) -> MagicMock:
            if was_called.is_set():
                raise RuntimeError("Must be called once.")
            was_called.set()
            mock_ssl_socket.fileno.side_effect = None
            mock_ssl_socket.fileno.return_value = sock.detach()
            del sock
            mock_ssl_socket.context = ssl_context
            mock_ssl_socket.getpeercert.return_value = mocker.sentinel.peercert
            mock_ssl_socket.cipher.return_value = mocker.sentinel.cipher
            mock_ssl_socket.compression.return_value = mocker.sentinel.compression
            mock_ssl_socket.version.return_value = mocker.sentinel.tls_version
            mock_ssl_socket.setblocking(False)
            try:
                mock_ssl_socket.do_handshake()
            except BaseException:
                mock_ssl_socket.close()
                raise
            mock_ssl_stream_transport.extra_attributes = {
                **_get_socket_extra(mock_ssl_socket, wrap_in_proxy=False),
                **_get_tls_extra(mock_ssl_socket, kwargs.get("standard_compatible", True)),
            }
            return mock_ssl_stream_transport

        return mocker.patch(
            f"{SSLStreamTransport.__module__}.SSLStreamTransport",
            side_effect=mock_transport_side_effect,
        )

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_ssl_create_default_context(mock_ssl_context: MagicMock, mocker: MockerFixture) -> MagicMock:
        return mocker.patch("ssl.create_default_context", autospec=True, side_effect=[mock_ssl_context])

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_socket_create_connection(mocker: MockerFixture, mock_tcp_socket: MagicMock) -> MagicMock:
        return mocker.patch("socket.create_connection", autospec=True, side_effect=[mock_tcp_socket])

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_used_socket(mock_tcp_socket: MagicMock, mock_ssl_socket: MagicMock, use_ssl: bool) -> MagicMock:
        return mock_ssl_socket if use_ssl else mock_tcp_socket

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_stream_transport(
        mock_socket_stream_transport: MagicMock,
        mock_ssl_stream_transport: MagicMock,
        use_ssl: bool,
    ) -> MagicMock:
        return mock_ssl_stream_transport if use_ssl else mock_socket_stream_transport

    @pytest.fixture(autouse=True)
    @staticmethod
    def set_default_socket_mock_configuration(
        mock_tcp_socket: MagicMock,
        mock_ssl_socket: MagicMock,
        socket_family: int,
    ) -> None:
        for mock_used_socket in (mock_tcp_socket, mock_ssl_socket):
            mock_used_socket.family = socket_family
            mock_used_socket.getsockopt.return_value = 0  # Needed for tests dealing with send_packet()

    @pytest.fixture
    @staticmethod
    def client(
        use_ssl: bool,
        mock_tcp_socket: MagicMock,
        mock_stream_protocol: MagicMock,
    ) -> Iterator[TCPNetworkClient[Any, Any]]:
        client: TCPNetworkClient[Any, Any] = TCPNetworkClient(
            mock_tcp_socket,
            mock_stream_protocol,
            ssl=use_ssl,
            server_hostname="server_hostname" if use_ssl else None,
        )

        with client:
            yield client

    @pytest.fixture(
        params=[
            pytest.param(None, id="blocking (None)"),
            pytest.param(float("+inf"), id="blocking (+inf)"),
            pytest.param(0, id="non_blocking"),
            pytest.param(123456789, id="with_timeout"),
        ]
    )
    @staticmethod
    def recv_timeout(request: pytest.FixtureRequest) -> float:
        return request.param

    @pytest.fixture(
        params=[
            pytest.param(None, id="blocking (None)"),
            pytest.param(float("+inf"), id="blocking (+inf)"),
            pytest.param(0, id="non_blocking"),
            pytest.param(123456789, id="with_timeout"),
        ]
    )
    @staticmethod
    def send_timeout(request: pytest.FixtureRequest) -> float:
        return request.param

    @pytest.mark.parametrize("max_recv_size", [None, 123456789], ids=lambda p: f"max_recv_size=={p}")
    @pytest.mark.parametrize("retry_interval", [1.0, float("+inf")], ids=lambda p: f"retry_interval=={p}")
    def test____dunder_init____connect_to_remote(
        self,
        request: pytest.FixtureRequest,
        max_recv_size: int | None,
        retry_interval: float,
        local_address: tuple[str, int],
        remote_address: tuple[str, int],
        mock_tcp_socket: MagicMock,
        mock_socket_create_connection: MagicMock,
        mock_socket_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_stream_endpoint_cls: MagicMock,
        mock_socket_stream_transport_cls: MagicMock,
        mock_ssl_stream_transport_cls: MagicMock,
        mock_ssl_create_default_context: MagicMock,
        mock_ssl_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        expected_max_recv_size: int = DEFAULT_STREAM_BUFSIZE if max_recv_size is None else max_recv_size

        # Act
        client = TCPNetworkClient[Any, Any](
            remote_address,
            protocol=mock_stream_protocol,
            connect_timeout=mocker.sentinel.timeout,
            local_address=local_address,
            max_recv_size=max_recv_size,
            retry_interval=retry_interval,
        )
        request.addfinalizer(client.close)

        # Assert
        mock_socket_create_connection.assert_called_once_with(
            remote_address,
            timeout=mocker.sentinel.timeout,
            source_address=local_address,
            all_errors=True,
        )
        mock_ssl_create_default_context.assert_not_called()
        mock_socket_stream_transport_cls.assert_called_once_with(mock_tcp_socket, retry_interval=retry_interval)
        mock_ssl_stream_transport_cls.assert_not_called()
        mock_stream_endpoint_cls.assert_called_once_with(
            mock_socket_stream_transport,
            mock_stream_protocol,
            max_recv_size=expected_max_recv_size,
        )
        assert mock_tcp_socket.mock_calls == [
            mocker.call.getpeername(),
            mocker.call.setblocking(False),
            mocker.call.setsockopt(IPPROTO_TCP, TCP_NODELAY, True),
            mocker.call.setsockopt(SOL_SOCKET, SO_KEEPALIVE, True),
        ]
        assert mock_ssl_socket.mock_calls == []
        assert isinstance(client.socket, SocketProxy)

    @pytest.mark.parametrize("max_recv_size", [None, 123456789], ids=lambda p: f"max_recv_size=={p}")
    @pytest.mark.parametrize("retry_interval", [1.0, float("+inf")], ids=lambda p: f"retry_interval=={p}")
    def test____dunder_init____use_given_socket(
        self,
        request: pytest.FixtureRequest,
        max_recv_size: int | None,
        retry_interval: float,
        mock_tcp_socket: MagicMock,
        mock_socket_create_connection: MagicMock,
        mock_socket_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_stream_endpoint_cls: MagicMock,
        mock_socket_stream_transport_cls: MagicMock,
        mock_ssl_stream_transport_cls: MagicMock,
        mock_ssl_create_default_context: MagicMock,
        mock_ssl_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        expected_max_recv_size: int = DEFAULT_STREAM_BUFSIZE if max_recv_size is None else max_recv_size

        # Act
        client = TCPNetworkClient[Any, Any](
            mock_tcp_socket,
            protocol=mock_stream_protocol,
            max_recv_size=max_recv_size,
            retry_interval=retry_interval,
        )
        request.addfinalizer(client.close)

        mock_socket_create_connection.assert_not_called()
        mock_ssl_create_default_context.assert_not_called()
        mock_socket_stream_transport_cls.assert_called_once_with(mock_tcp_socket, retry_interval=retry_interval)
        mock_ssl_stream_transport_cls.assert_not_called()
        mock_stream_endpoint_cls.assert_called_once_with(
            mock_socket_stream_transport,
            mock_stream_protocol,
            max_recv_size=expected_max_recv_size,
        )
        assert mock_tcp_socket.mock_calls == [
            mocker.call.getpeername(),
            mocker.call.setblocking(False),
            mocker.call.setsockopt(IPPROTO_TCP, TCP_NODELAY, True),
            mocker.call.setsockopt(SOL_SOCKET, SO_KEEPALIVE, True),
        ]
        assert mock_ssl_socket.mock_calls == []
        assert isinstance(client.socket, SocketProxy)

    @pytest.mark.parametrize("socket_family", list(unsupported_families(INET_FAMILIES)), indirect=True)
    def test____dunder_init____use_given_socket____invalid_socket_family(
        self,
        use_ssl: bool,
        mock_tcp_socket: MagicMock,
        mock_ssl_socket: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_ssl_create_default_context: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        server_hostname: str | None = None
        if use_ssl:
            server_hostname = "test.example.com"

        # Act & Assert
        with pytest.raises(ValueError, match=r"^Only these families are supported: .+$"):
            _ = TCPNetworkClient(
                mock_tcp_socket,
                protocol=mock_stream_protocol,
                ssl=use_ssl,
                server_hostname=server_hostname,
            )

        mock_ssl_create_default_context.assert_not_called()
        assert mock_tcp_socket.mock_calls == [mocker.call.close()]
        assert mock_ssl_socket.mock_calls == []

    def test____dunder_init____use_given_socket____error_no_remote_address(
        self,
        use_ssl: bool,
        mock_tcp_socket: MagicMock,
        mock_socket_create_connection: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_ssl_create_default_context: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        enotconn_exception = self.configure_socket_mock_to_raise_ENOTCONN(mock_tcp_socket)
        server_hostname: str | None = None
        if use_ssl:
            server_hostname = "test.example.com"

        # Act
        with pytest.raises(OSError) as exc_info:
            _ = TCPNetworkClient(
                mock_tcp_socket,
                protocol=mock_stream_protocol,
                ssl=use_ssl,
                server_hostname=server_hostname,
            )

        # Assert
        assert exc_info.value.errno == enotconn_exception.errno
        mock_socket_create_connection.assert_not_called()
        mock_ssl_create_default_context.assert_not_called()
        assert mock_tcp_socket.mock_calls == [mocker.call.getpeername(), mocker.call.close()]

    def test____dunder_init____invalid_first_argument____invalid_object(
        self,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        invalid_object = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Invalid arguments$"):
            _ = TCPNetworkClient(
                invalid_object,
                protocol=mock_stream_protocol,
            )

    def test____dunder_init____invalid_first_argument____invalid_host_port_pair(
        self,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        invalid_host = mocker.NonCallableMagicMock(spec=object)
        invalid_port = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Invalid arguments$"):
            _ = TCPNetworkClient(
                (invalid_host, invalid_port),
                protocol=mock_stream_protocol,
            )

    def test____dunder_init____invalid_arguments____unknown_overload(
        self,
        local_address: tuple[str, int],
        mock_tcp_socket: MagicMock,
        mock_stream_protocol: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Invalid arguments$"):
            _ = TCPNetworkClient(
                mock_tcp_socket,
                protocol=mock_stream_protocol,
                local_address=local_address,
                connect_timeout=123,
            )

        assert mock_tcp_socket.mock_calls == []

    @pytest.mark.parametrize("use_socket", [False, True], ids=lambda p: f"use_socket=={p}")
    def test____dunder_init____protocol____invalid_value(
        self,
        use_socket: bool,
        remote_address: tuple[str, int],
        mock_tcp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a StreamProtocol or a BufferedStreamProtocol object, got .*$"):
            if use_socket:
                _ = TCPNetworkClient(
                    mock_tcp_socket,
                    protocol=mock_datagram_protocol,
                )
            else:
                _ = TCPNetworkClient(
                    remote_address,
                    protocol=mock_datagram_protocol,
                )

    @pytest.mark.parametrize("max_recv_size", [0, -1, 10.4], ids=lambda p: f"max_recv_size=={p}")
    @pytest.mark.parametrize("use_socket", [False, True], ids=lambda p: f"use_socket=={p}")
    def test____dunder_init____max_recv_size____invalid_value(
        self,
        max_recv_size: Any,
        use_socket: bool,
        remote_address: tuple[str, int],
        mock_stream_endpoint_cls: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_tcp_socket: MagicMock,
        mock_socket_stream_transport: MagicMock,
    ) -> None:
        # Arrange
        ## The check is performed by the StreamEndpoint constructor, so we simulate an error raised.
        mock_stream_endpoint_cls.side_effect = ValueError("'max_recv_size' must be a strictly positive integer")

        # Act & Assert
        with pytest.raises(ValueError, match=r"^'max_recv_size' must be a strictly positive integer$"):
            if use_socket:
                _ = TCPNetworkClient(
                    mock_tcp_socket,
                    protocol=mock_stream_protocol,
                    max_recv_size=max_recv_size,
                )
            else:
                _ = TCPNetworkClient(
                    remote_address,
                    protocol=mock_stream_protocol,
                    max_recv_size=max_recv_size,
                )
        mock_stream_endpoint_cls.assert_called_once_with(
            mock_socket_stream_transport,
            mock_stream_protocol,
            max_recv_size=max_recv_size,
        )
        mock_socket_stream_transport.close.assert_called_once()

    @pytest.mark.parametrize("use_socket", [False, True], ids=lambda p: f"use_socket=={p}")
    @pytest.mark.parametrize("max_recv_size", [None, 123456789], ids=lambda p: f"max_recv_size=={p}")
    @pytest.mark.parametrize("retry_interval", [1.0, float("+inf")], ids=lambda p: f"retry_interval=={p}")
    def test____dunder_init____ssl(
        self,
        request: pytest.FixtureRequest,
        max_recv_size: int | None,
        retry_interval: float,
        use_socket: bool,
        local_address: tuple[str, int],
        remote_address: tuple[str, int],
        mock_tcp_socket: MagicMock,
        mock_socket_create_connection: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_stream_endpoint_cls: MagicMock,
        mock_socket_stream_transport_cls: MagicMock,
        mock_ssl_stream_transport: MagicMock,
        mock_ssl_stream_transport_cls: MagicMock,
        mock_ssl_create_default_context: MagicMock,
        mock_ssl_context: MagicMock,
        mock_ssl_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        expected_max_recv_size: int = DEFAULT_STREAM_BUFSIZE if max_recv_size is None else max_recv_size

        # Act
        client: TCPNetworkClient[Any, Any]
        if use_socket:
            client = TCPNetworkClient(
                mock_tcp_socket,
                protocol=mock_stream_protocol,
                ssl=mock_ssl_context,
                server_hostname="server_hostname",
                ssl_handshake_timeout=mocker.sentinel.ssl_handshake_timeout,
                ssl_shutdown_timeout=mocker.sentinel.ssl_shutdown_timeout,
                ssl_standard_compatible=mocker.sentinel.ssl_standard_compatible,
                max_recv_size=max_recv_size,
                retry_interval=retry_interval,
            )
        else:
            client = TCPNetworkClient(
                remote_address,
                protocol=mock_stream_protocol,
                ssl=mock_ssl_context,
                server_hostname="server_hostname",
                ssl_handshake_timeout=mocker.sentinel.ssl_handshake_timeout,
                ssl_shutdown_timeout=mocker.sentinel.ssl_shutdown_timeout,
                ssl_standard_compatible=mocker.sentinel.ssl_standard_compatible,
                connect_timeout=mocker.sentinel.timeout,
                local_address=local_address,
                max_recv_size=max_recv_size,
                retry_interval=retry_interval,
            )
        request.addfinalizer(client.close)

        # Assert
        mock_ssl_create_default_context.assert_not_called()
        if use_socket:
            mock_socket_create_connection.assert_not_called()
        else:
            mock_socket_create_connection.assert_called_once_with(
                remote_address,
                timeout=mocker.sentinel.timeout,
                source_address=local_address,
                all_errors=True,
            )

        assert mock_tcp_socket.mock_calls == [
            mocker.call.getpeername(),
            mocker.call.detach(),
        ]
        assert mock_ssl_socket.mock_calls == [
            mocker.call.setblocking(False),
            mocker.call.do_handshake(),
            mocker.call.setsockopt(IPPROTO_TCP, TCP_NODELAY, True),
            mocker.call.setsockopt(SOL_SOCKET, SO_KEEPALIVE, True),
        ]
        assert mock_tcp_socket.fileno() == -1

        mock_socket_stream_transport_cls.assert_not_called()
        mock_ssl_stream_transport_cls.assert_called_once_with(
            mock_tcp_socket,
            ssl_context=mock_ssl_context,
            retry_interval=retry_interval,
            server_hostname="server_hostname",
            server_side=False,
            handshake_timeout=mocker.sentinel.ssl_handshake_timeout,
            shutdown_timeout=mocker.sentinel.ssl_shutdown_timeout,
            standard_compatible=mocker.sentinel.ssl_standard_compatible,
        )
        mock_stream_endpoint_cls.assert_called_once_with(
            mock_ssl_stream_transport,
            mock_stream_protocol,
            max_recv_size=expected_max_recv_size,
        )
        assert isinstance(client.socket, SocketProxy)

    @pytest.mark.parametrize("use_socket", [False, True], ids=lambda p: f"use_socket=={p}")
    @pytest.mark.parametrize("max_recv_size", [None, 123456789], ids=lambda p: f"max_recv_size=={p}")
    @pytest.mark.parametrize("retry_interval", [1.0, float("+inf")], ids=lambda p: f"retry_interval=={p}")
    def test____dunder_init____ssl____default_values(
        self,
        request: pytest.FixtureRequest,
        max_recv_size: int | None,
        retry_interval: float,
        use_socket: bool,
        local_address: tuple[str, int],
        remote_address: tuple[str, int],
        mock_tcp_socket: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_ssl_stream_transport_cls: MagicMock,
        mock_ssl_context: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        client: TCPNetworkClient[Any, Any]
        if use_socket:
            client = TCPNetworkClient(
                mock_tcp_socket,
                protocol=mock_stream_protocol,
                ssl=mock_ssl_context,
                server_hostname="server_hostname",
                max_recv_size=max_recv_size,
                retry_interval=retry_interval,
            )
        else:
            client = TCPNetworkClient(
                remote_address,
                protocol=mock_stream_protocol,
                ssl=mock_ssl_context,
                server_hostname="server_hostname",
                connect_timeout=mocker.sentinel.timeout,
                local_address=local_address,
                max_recv_size=max_recv_size,
                retry_interval=retry_interval,
            )
        request.addfinalizer(client.close)

        # Assert
        mock_ssl_stream_transport_cls.assert_called_once_with(
            mock_tcp_socket,
            ssl_context=mock_ssl_context,
            retry_interval=retry_interval,
            server_hostname="server_hostname",
            server_side=False,
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
    def test____dunder_init____ssl____useless_parameter_if_no_context(
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
                _ = TCPNetworkClient(
                    mock_tcp_socket,
                    protocol=mock_stream_protocol,
                    ssl=None,
                    **kwargs,
                )
            else:
                _ = TCPNetworkClient(
                    remote_address,
                    protocol=mock_stream_protocol,
                    ssl=None,
                    **kwargs,
                )

    def test____dunder_init____ssl____server_hostname____use_remote_host_by_default(
        self,
        request: pytest.FixtureRequest,
        remote_address: tuple[str, int],
        mock_ssl_context: MagicMock,
        mock_tcp_socket: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_ssl_stream_transport_cls: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        remote_host, _ = remote_address

        # Act
        client = TCPNetworkClient[Any, Any](
            remote_address,
            protocol=mock_stream_protocol,
            ssl=mock_ssl_context,
            server_hostname=None,
        )
        request.addfinalizer(client.close)

        # Assert
        mock_ssl_stream_transport_cls.assert_called_once_with(
            mock_tcp_socket,
            ssl_context=mock_ssl_context,
            retry_interval=mocker.ANY,
            server_hostname=remote_host,
            server_side=False,
            handshake_timeout=None,
            shutdown_timeout=None,
            standard_compatible=True,
        )

    @pytest.mark.parametrize("use_socket", [False, True], ids=lambda p: f"use_socket=={p}")
    def test____dunder_init____ssl____server_hostname____do_not_disable_hostname_check_for_external_context(
        self,
        request: pytest.FixtureRequest,
        use_socket: bool,
        remote_address: tuple[str, int],
        mock_ssl_context: MagicMock,
        mock_tcp_socket: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_ssl_stream_transport_cls: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        assert mock_ssl_context.check_hostname

        # Act
        client: TCPNetworkClient[Any, Any]
        if use_socket:
            client = TCPNetworkClient(
                mock_tcp_socket,
                protocol=mock_stream_protocol,
                ssl=mock_ssl_context,
                server_hostname="",
            )
        else:
            client = TCPNetworkClient(
                remote_address,
                protocol=mock_stream_protocol,
                ssl=mock_ssl_context,
                server_hostname="",
            )
        request.addfinalizer(client.close)

        # Assert
        assert mock_ssl_context.check_hostname is True
        mock_ssl_stream_transport_cls.assert_called_once_with(
            mock_tcp_socket,
            ssl_context=mock_ssl_context,
            retry_interval=mocker.ANY,
            server_hostname=None,
            server_side=False,
            handshake_timeout=None,
            shutdown_timeout=None,
            standard_compatible=True,
        )

    @pytest.mark.parametrize("use_socket", [False, True], ids=lambda p: f"use_socket=={p}")
    def test____dunder_init____ssl____server_hostname____no_host_to_use(
        self,
        use_socket: bool,
        remote_address: tuple[str, int],
        mock_tcp_socket: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_ssl_context: MagicMock,
    ) -> None:
        # Arrange
        remote_address = ("", remote_address[1])

        # Act & Assert
        with pytest.raises(ValueError, match=r"^You must set server_hostname when using ssl without a host$"):
            if use_socket:
                _ = TCPNetworkClient(
                    mock_tcp_socket,
                    protocol=mock_stream_protocol,
                    ssl=mock_ssl_context,
                    server_hostname=None,
                )
            else:
                _ = TCPNetworkClient(
                    remote_address,
                    protocol=mock_stream_protocol,
                    ssl=mock_ssl_context,
                    server_hostname=None,
                )

    @pytest.mark.parametrize("use_socket", [False, True], ids=lambda p: f"use_socket=={p}")
    @pytest.mark.parametrize("OP_IGNORE_UNEXPECTED_EOF", [False, True], ids=lambda p: f"OP_IGNORE_UNEXPECTED_EOF=={p}")
    def test____dunder_init____ssl____create_default_context(
        self,
        request: pytest.FixtureRequest,
        use_socket: bool,
        OP_IGNORE_UNEXPECTED_EOF: bool,
        remote_address: tuple[str, int],
        mock_ssl_context: MagicMock,
        mock_tcp_socket: MagicMock,
        mock_ssl_create_default_context: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_ssl_stream_transport_cls: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        if not OP_IGNORE_UNEXPECTED_EOF:
            monkeypatch.delattr("ssl.OP_IGNORE_UNEXPECTED_EOF", raising=False)
        elif not hasattr(ssl, "OP_IGNORE_UNEXPECTED_EOF"):
            pytest.skip("ssl.OP_IGNORE_UNEXPECTED_EOF not defined")

        # Act
        client: TCPNetworkClient[Any, Any]
        if use_socket:
            client = TCPNetworkClient(
                mock_tcp_socket,
                protocol=mock_stream_protocol,
                ssl=True,
                server_hostname="server_hostname",
            )
        else:
            client = TCPNetworkClient(
                remote_address,
                protocol=mock_stream_protocol,
                ssl=True,
                server_hostname="server_hostname",
            )
        request.addfinalizer(client.close)

        # Assert
        mock_ssl_create_default_context.assert_called_once_with()
        mock_ssl_stream_transport_cls.assert_called_once_with(
            mock_tcp_socket,
            ssl_context=mock_ssl_context,
            retry_interval=mocker.ANY,
            server_hostname="server_hostname",
            server_side=False,
            handshake_timeout=None,
            shutdown_timeout=None,
            standard_compatible=True,
        )

    @pytest.mark.parametrize("use_socket", [False, True], ids=lambda p: f"use_socket=={p}")
    def test____dunder_init____ssl____create_default_context____disable_hostname_check(
        self,
        request: pytest.FixtureRequest,
        use_socket: bool,
        remote_address: tuple[str, int],
        mock_ssl_context: MagicMock,
        mock_tcp_socket: MagicMock,
        mock_ssl_create_default_context: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_ssl_stream_transport_cls: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        check_hostname_by_default: bool = mock_ssl_context.check_hostname
        assert check_hostname_by_default

        # Act
        client: TCPNetworkClient[Any, Any]
        if use_socket:
            client = TCPNetworkClient(
                mock_tcp_socket,
                protocol=mock_stream_protocol,
                ssl=True,
                server_hostname="",
            )
        else:
            client = TCPNetworkClient(
                remote_address,
                protocol=mock_stream_protocol,
                ssl=True,
                server_hostname="",
            )
        request.addfinalizer(client.close)

        # Assert
        mock_ssl_create_default_context.assert_called_once_with()
        mock_ssl_stream_transport_cls.assert_called_once_with(
            mock_tcp_socket,
            ssl_context=mock_ssl_context,
            retry_interval=mocker.ANY,
            server_hostname=None,
            server_side=False,
            handshake_timeout=None,
            shutdown_timeout=None,
            standard_compatible=True,
        )
        assert mock_ssl_context.check_hostname is False

    def test____dunder_del____ResourceWarning(
        self,
        mock_stream_endpoint: MagicMock,
        mock_stream_protocol: MagicMock,
        remote_address: tuple[str, int],
    ) -> None:
        # Arrange
        client: TCPNetworkClient[Any, Any] = TCPNetworkClient(remote_address, mock_stream_protocol)

        # Act & Assert
        with pytest.warns(ResourceWarning, match=r"^unclosed client .+$"):
            del client

        mock_stream_endpoint.close.assert_called_once_with()

    def test____close____default(
        self,
        client: TCPNetworkClient[Any, Any],
        mock_stream_endpoint: MagicMock,
    ) -> None:
        # Arrange
        assert not client.is_closed()

        # Act
        client.close()

        # Assert
        assert client.is_closed()
        mock_stream_endpoint.close.assert_called_once_with()

    def test____get_local_address____ask_for_address(
        self,
        client: TCPNetworkClient[Any, Any],
        socket_family: int,
        local_address: tuple[str, int],
        mock_used_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_used_socket.getsockname.reset_mock()

        # Act
        address = client.get_local_address()

        # Assert
        if socket_family == AF_INET6:
            assert isinstance(address, IPv6SocketAddress)
        else:
            assert isinstance(address, IPv4SocketAddress)
        mock_used_socket.getsockname.assert_called_once()
        assert address.host == local_address[0]
        assert address.port == local_address[1]

    def test____get_remote_address____ask_for_address(
        self,
        client: TCPNetworkClient[Any, Any],
        remote_address: tuple[str, int],
        socket_family: int,
        mock_used_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_used_socket.getpeername.reset_mock()

        # Act
        address = client.get_remote_address()

        # Assert
        if socket_family == AF_INET6:
            assert isinstance(address, IPv6SocketAddress)
        else:
            assert isinstance(address, IPv4SocketAddress)
        mock_used_socket.getpeername.assert_called_once()
        assert address.host == remote_address[0]
        assert address.port == remote_address[1]

    def test____get_local_or_remote_address____closed_client(
        self,
        client: TCPNetworkClient[Any, Any],
        mock_used_socket: MagicMock,
    ) -> None:
        # Arrange
        client.close()
        mock_used_socket.reset_mock()

        # Act & Assert
        with pytest.raises(ClientClosedError):
            client.get_local_address()
        with pytest.raises(ClientClosedError):
            client.get_remote_address()

        mock_used_socket.getsockname.assert_not_called()
        mock_used_socket.getpeername.assert_not_called()

    def test____fileno____default(
        self,
        client: TCPNetworkClient[Any, Any],
        mock_used_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act
        fd = client.fileno()

        # Assert
        mock_used_socket.fileno.assert_called_once_with()
        assert fd == mock_used_socket.fileno.return_value

    def test____socket_property____cached_attribute(
        self,
        client: TCPNetworkClient[Any, Any],
    ) -> None:
        # Arrange

        # Act & Assert
        assert client.socket is client.socket

    def test____send_packet____send_bytes_to_socket(
        self,
        client: TCPNetworkClient[Any, Any],
        send_timeout: float | None,
        mock_used_socket: MagicMock,
        mock_stream_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        client.send_packet(mocker.sentinel.packet, timeout=send_timeout)

        # Assert
        mock_stream_endpoint.send_packet.assert_called_once_with(mocker.sentinel.packet, timeout=send_timeout)
        mock_used_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_ERROR)

    def test____send_packet____raise_error_saved_in_SO_ERROR_option(
        self,
        client: TCPNetworkClient[Any, Any],
        send_timeout: float | None,
        mock_used_socket: MagicMock,
        mock_stream_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_used_socket.getsockopt.return_value = errno.EBUSY

        # Act
        with pytest.raises(OSError) as exc_info:
            client.send_packet(mocker.sentinel.packet, timeout=send_timeout)

        # Assert
        assert exc_info.value.errno == errno.EBUSY
        mock_stream_endpoint.send_packet.assert_called_once_with(mocker.sentinel.packet, timeout=send_timeout)
        mock_used_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_ERROR)

    def test____send_packet____closed_client_error(
        self,
        client: TCPNetworkClient[Any, Any],
        send_timeout: float | None,
        mock_used_socket: MagicMock,
        mock_stream_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        client.close()
        assert client.is_closed()

        # Act
        with pytest.raises(ClientClosedError):
            client.send_packet(mocker.sentinel.packet, timeout=send_timeout)

        # Assert
        mock_stream_endpoint.send_packet.assert_not_called()
        mock_used_socket.getsockopt.assert_not_called()

    def test____send_packet____convert_connection_errors(
        self,
        client: TCPNetworkClient[Any, Any],
        send_timeout: float | None,
        mock_used_socket: MagicMock,
        mock_stream_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_endpoint.send_packet.side_effect = ConnectionError

        # Act
        with pytest.raises(ConnectionAbortedError):
            client.send_packet(mocker.sentinel.packet, timeout=send_timeout)

        # Assert
        mock_stream_endpoint.send_packet.assert_called_once_with(mocker.sentinel.packet, timeout=send_timeout)
        mock_stream_endpoint.close.assert_not_called()
        mock_used_socket.getsockopt.assert_not_called()

    @pytest.mark.parametrize("closed_socket_errno", sorted(CLOSED_SOCKET_ERRNOS), ids=errno.errorcode.__getitem__)
    def test____send_packet____convert_closed_socket_errors(
        self,
        closed_socket_errno: int,
        client: TCPNetworkClient[Any, Any],
        send_timeout: float | None,
        mock_used_socket: MagicMock,
        mock_stream_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_endpoint.send_packet.side_effect = OSError(closed_socket_errno, os.strerror(closed_socket_errno))

        # Act
        with pytest.raises(OSError) as exc_info:
            client.send_packet(mocker.sentinel.packet, timeout=send_timeout)

        # Assert
        assert exc_info.value.errno == closed_socket_errno
        assert exc_info.value.__notes__ == ["The socket file descriptor was closed unexpectedly."]
        assert not client.is_closed()
        mock_stream_endpoint.send_packet.assert_called_once_with(mocker.sentinel.packet, timeout=send_timeout)
        mock_stream_endpoint.close.assert_not_called()
        mock_used_socket.getsockopt.assert_not_called()

    @pytest.mark.parametrize("use_ssl", ["USE_SSL"], indirect=True)
    def test____send_packet____ssl____eof_error(
        self,
        client: TCPNetworkClient[Any, Any],
        send_timeout: float | None,
        mock_used_socket: MagicMock,
        mock_stream_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_endpoint.send_packet.side_effect = SSLEOFError

        # Act
        with pytest.raises(ConnectionAbortedError):
            client.send_packet(mocker.sentinel.packet, timeout=send_timeout)

        # Assert
        mock_stream_endpoint.send_packet.assert_called_once_with(mocker.sentinel.packet, timeout=send_timeout)
        mock_used_socket.getsockopt.assert_not_called()

    @pytest.mark.parametrize("use_ssl", ["USE_SSL"], indirect=True)
    def test____send_packet____ssl____unrelated_ssl_error(
        self,
        client: TCPNetworkClient[Any, Any],
        send_timeout: float | None,
        mock_used_socket: MagicMock,
        mock_stream_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_endpoint.send_packet.side_effect = SSLError(SSLErrorNumber.SSL_ERROR_INVALID_ERROR_CODE, "SOMETHING")

        # Act
        with pytest.raises(SSLError) as exc_info:
            client.send_packet(mocker.sentinel.packet, timeout=send_timeout)

        # Assert
        assert exc_info.value is mock_stream_endpoint.send_packet.side_effect
        mock_stream_endpoint.send_packet.assert_called_once_with(mocker.sentinel.packet, timeout=send_timeout)
        mock_used_socket.getsockopt.assert_not_called()

    @pytest.mark.parametrize("use_ssl", ["NO_SSL"], indirect=True)
    def test____send_eof____socket_send_eof(
        self,
        client: TCPNetworkClient[Any, Any],
        mock_stream_endpoint: MagicMock,
    ) -> None:
        # Arrange

        # Act
        client.send_eof()

        # Assert
        mock_stream_endpoint.send_eof.assert_called_once_with()
        mock_stream_endpoint.close.assert_not_called()

    @pytest.mark.parametrize("use_ssl", ["NO_SSL"], indirect=True)
    def test____send_eof____closed_client(
        self,
        client: TCPNetworkClient[Any, Any],
        mock_stream_endpoint: MagicMock,
    ) -> None:
        # Arrange
        client.close()

        # Act
        client.send_eof()

        # Assert
        mock_stream_endpoint.send_eof.assert_not_called()

    @pytest.mark.parametrize("closed_socket_errno", sorted(CLOSED_SOCKET_ERRNOS), ids=errno.errorcode.__getitem__)
    @pytest.mark.parametrize("use_ssl", ["NO_SSL"], indirect=True)
    def test____send_eof____closed_socket_error(
        self,
        closed_socket_errno: int,
        client: TCPNetworkClient[Any, Any],
        mock_stream_endpoint: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_endpoint.send_eof.side_effect = OSError(closed_socket_errno, os.strerror(closed_socket_errno))

        # Act
        with pytest.raises(OSError) as exc_info:
            client.send_eof()

        # Assert
        assert exc_info.value.errno == closed_socket_errno
        assert exc_info.value.__notes__ == ["The socket file descriptor was closed unexpectedly."]
        assert not client.is_closed()
        mock_stream_endpoint.send_eof.assert_called_once_with()
        mock_stream_endpoint.close.assert_not_called()

    def test____recv_packet____receive_bytes_from_socket(
        self,
        client: TCPNetworkClient[Any, Any],
        recv_timeout: float | None,
        mock_stream_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_endpoint.recv_packet.side_effect = [mocker.sentinel.packet]

        # Act
        packet: Any = client.recv_packet(timeout=recv_timeout)

        # Assert
        mock_stream_endpoint.recv_packet.assert_called_once_with(timeout=recv_timeout)
        assert packet is mocker.sentinel.packet

    def test____recv_packet____protocol_parse_error(
        self,
        client: TCPNetworkClient[Any, Any],
        recv_timeout: float | None,
        mock_stream_endpoint: MagicMock,
    ) -> None:
        # Arrange
        expected_error = StreamProtocolParseError(b"", IncrementalDeserializeError("Sorry", b""))
        mock_stream_endpoint.recv_packet.side_effect = [expected_error]

        # Act
        with pytest.raises(StreamProtocolParseError) as exc_info:
            _ = client.recv_packet(timeout=recv_timeout)

        # Assert
        assert exc_info.value is expected_error

    def test____recv_packet____closed_client_error(
        self,
        client: TCPNetworkClient[Any, Any],
        recv_timeout: float | None,
        mock_stream_endpoint: MagicMock,
    ) -> None:
        # Arrange
        client.close()
        assert client.is_closed()

        # Act
        with pytest.raises(ClientClosedError):
            _ = client.recv_packet(timeout=recv_timeout)

        # Assert
        mock_stream_endpoint.recv_packet.assert_not_called()

    def test____recv_packet____convert_connection_errors(
        self,
        client: TCPNetworkClient[Any, Any],
        recv_timeout: float | None,
        mock_stream_endpoint: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_endpoint.recv_packet.side_effect = ConnectionError

        # Act
        with pytest.raises(ConnectionAbortedError):
            _ = client.recv_packet(timeout=recv_timeout)

        # Assert
        mock_stream_endpoint.recv_packet.assert_called_once_with(timeout=recv_timeout)

    @pytest.mark.parametrize("use_ssl", ["USE_SSL"], indirect=True)
    def test____recv_packet____ssl____unrelated_ssl_error(
        self,
        client: TCPNetworkClient[Any, Any],
        recv_timeout: float | None,
        mock_stream_endpoint: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_endpoint.recv_packet.side_effect = ssl.SSLError(
            ssl.SSLErrorNumber.SSL_ERROR_INVALID_ERROR_CODE,
            "SOMETHING",
        )

        # Act
        with pytest.raises(ssl.SSLError) as exc_info:
            _ = client.recv_packet(timeout=recv_timeout)

        # Assert
        assert exc_info.value.errno == ssl.SSLErrorNumber.SSL_ERROR_INVALID_ERROR_CODE
        assert exc_info.value.strerror == "SOMETHING"
        mock_stream_endpoint.recv_packet.assert_called_once_with(timeout=recv_timeout)

    @pytest.mark.parametrize("use_ssl", ["USE_SSL"], indirect=True)
    def test____recv_packet____ssl____ragged_eof_error(
        self,
        client: TCPNetworkClient[Any, Any],
        recv_timeout: float | None,
        mock_stream_endpoint: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_endpoint.recv_packet.side_effect = ssl.SSLEOFError()

        # Act
        with pytest.raises(ConnectionAbortedError):
            _ = client.recv_packet(timeout=recv_timeout)

        # Assert
        mock_stream_endpoint.recv_packet.assert_called_once_with(timeout=recv_timeout)

    @pytest.mark.parametrize("closed_socket_errno", sorted(CLOSED_SOCKET_ERRNOS), ids=errno.errorcode.__getitem__)
    def test____recv_packet____convert_closed_socket_errors(
        self,
        closed_socket_errno: int,
        client: TCPNetworkClient[Any, Any],
        recv_timeout: float | None,
        mock_stream_endpoint: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_endpoint.recv_packet.side_effect = OSError(closed_socket_errno, os.strerror(closed_socket_errno))

        # Act
        with pytest.raises(OSError) as exc_info:
            _ = client.recv_packet(timeout=recv_timeout)

        # Assert
        assert exc_info.value.errno == closed_socket_errno
        assert exc_info.value.__notes__ == ["The socket file descriptor was closed unexpectedly."]
        assert not client.is_closed()
        mock_stream_endpoint.recv_packet.assert_called_once_with(timeout=recv_timeout)
        mock_stream_endpoint.close.assert_not_called()

    def test____special_case____separate_send_and_receive_locks(
        self,
        client: TCPNetworkClient[Any, Any],
        send_timeout: float | None,
        recv_timeout: float | None,
        mock_stream_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def recv_side_effect(**kwargs: Any) -> bytes:
            client.send_packet(mocker.sentinel.packet, timeout=send_timeout)
            raise ConnectionAbortedError

        mock_stream_endpoint.recv_packet.side_effect = recv_side_effect

        # Act
        with pytest.raises(ConnectionAbortedError):
            _ = client.recv_packet(timeout=recv_timeout)

        # Assert
        mock_stream_endpoint.send_packet.assert_called_once_with(mocker.sentinel.packet, timeout=send_timeout)

    @pytest.mark.parametrize("closed_socket_errno", sorted(CLOSED_SOCKET_ERRNOS), ids=errno.errorcode.__getitem__)
    def test____special_case____close_during_recv_call(
        self,
        closed_socket_errno: int,
        client: TCPNetworkClient[Any, Any],
        recv_timeout: float | None,
        mock_stream_endpoint: MagicMock,
    ) -> None:
        # Arrange
        def recv_side_effect(**kwargs: Any) -> bytes:
            client.close()
            raise OSError(closed_socket_errno, os.strerror(closed_socket_errno))

        mock_stream_endpoint.recv_packet.side_effect = recv_side_effect

        # Act & Assert
        with pytest.raises(ClientClosedError):
            _ = client.recv_packet(timeout=recv_timeout)
