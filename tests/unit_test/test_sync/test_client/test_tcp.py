from __future__ import annotations

import contextlib
import errno
import os
from collections.abc import Generator
from selectors import EVENT_READ, EVENT_WRITE
from socket import AF_INET6, IPPROTO_TCP, SHUT_RDWR, SHUT_WR, SO_KEEPALIVE, SOL_SOCKET, TCP_NODELAY
from ssl import SSLEOFError, SSLError, SSLErrorNumber, SSLWantReadError, SSLWantWriteError, SSLZeroReturnError
from typing import TYPE_CHECKING, Any

from easynetwork.api_sync.client.tcp import TCPNetworkClient
from easynetwork.exceptions import ClientClosedError, IncrementalDeserializeError
from easynetwork.lowlevel._stream import StreamDataConsumer
from easynetwork.lowlevel.constants import (
    CLOSED_SOCKET_ERRNOS,
    DEFAULT_STREAM_BUFSIZE,
    SSL_HANDSHAKE_TIMEOUT,
    SSL_SHUTDOWN_TIMEOUT,
)
from easynetwork.lowlevel.socket import IPv4SocketAddress, IPv6SocketAddress

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture

from ..._utils import DummyLock
from ...base import UNSUPPORTED_FAMILIES
from .base import BaseTestClient


@pytest.fixture(autouse=True)
def remove_ssl_OP_IGNORE_UNEXPECTED_EOF(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr("ssl.OP_IGNORE_UNEXPECTED_EOF", raising=False)


class TestTCPNetworkClient(BaseTestClient):
    @pytest.fixture(scope="class", params=["AF_INET", "AF_INET6"])
    @staticmethod
    def socket_family(request: Any) -> Any:
        import socket

        return getattr(socket, request.param)

    @pytest.fixture
    @staticmethod
    def socket_fileno() -> int:
        return 12345

    @pytest.fixture(scope="class")
    @staticmethod
    def global_local_address() -> tuple[str, int]:
        return ("local_address", 12345)

    @pytest.fixture(scope="class")
    @staticmethod
    def global_remote_address() -> tuple[str, int]:
        return ("remote_address", 5000)

    @pytest.fixture(params=["NO_SSL", "USE_SSL"])
    @staticmethod
    def use_ssl(request: Any) -> bool:
        match request.param:
            case "NO_SSL":
                return False
            case "USE_SSL":
                return True
            case _:
                pytest.fail("Invalid parameter")

    @pytest.fixture
    @staticmethod
    def mock_tcp_socket(mock_tcp_socket: MagicMock, socket_family: int, socket_fileno: int) -> MagicMock:
        mock_tcp_socket.family = socket_family
        mock_tcp_socket.fileno.return_value = socket_fileno
        return mock_tcp_socket

    @pytest.fixture
    @staticmethod
    def mock_ssl_socket(mock_ssl_socket: MagicMock, socket_family: int, socket_fileno: int) -> MagicMock:
        mock_ssl_socket.family = socket_family
        mock_ssl_socket.fileno.return_value = socket_fileno
        return mock_ssl_socket

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_used_socket(mock_tcp_socket: MagicMock, mock_ssl_socket: MagicMock, use_ssl: bool) -> MagicMock:
        mock_used_socket = mock_ssl_socket if use_ssl else mock_tcp_socket

        mock_used_socket.gettimeout.return_value = 0
        mock_used_socket.getsockopt.return_value = 0  # Needed for tests dealing with send_packet()
        mock_used_socket.send.side_effect = lambda data: len(data)
        del mock_used_socket.sendall
        del mock_used_socket.sendto

        return mock_used_socket

    @pytest.fixture
    @staticmethod
    def mock_used_socket_send(mock_used_socket: MagicMock) -> MagicMock:
        mock_used_socket_send: MagicMock = mock_used_socket.send
        mock_used_socket_send.side_effect = lambda data: len(data)

        # transport.send_all() will call send() with memoryviews and release the buffers after each call.
        # This is a workaround to use assert_called_with()
        mock_used_socket.send = lambda data: mock_used_socket_send(bytes(data))
        return mock_used_socket_send

    @pytest.fixture
    @staticmethod
    def mock_ssl_context(mock_ssl_context: MagicMock, mock_ssl_socket: MagicMock) -> MagicMock:
        def wrap_socket(sock: MagicMock, *args: Any, **kwargs: Any) -> MagicMock:
            sock.detach()
            return mock_ssl_socket

        mock_ssl_context.wrap_socket.side_effect = wrap_socket
        return mock_ssl_context

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_ssl_create_default_context(mock_ssl_context: MagicMock, mocker: MockerFixture) -> MagicMock:
        return mocker.patch("ssl.create_default_context", autospec=True, return_value=mock_ssl_context)

    @pytest.fixture
    @staticmethod
    def server_hostname(use_ssl: bool, mocker: MockerFixture) -> Any | None:
        return mocker.sentinel.server_hostname if use_ssl else None

    @pytest.fixture
    @staticmethod
    def ssl_context(use_ssl: bool, mock_ssl_context: MagicMock) -> MagicMock | None:
        return mock_ssl_context if use_ssl else None

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_socket_create_connection(mocker: MockerFixture, mock_tcp_socket: MagicMock) -> MagicMock:
        return mocker.patch("socket.create_connection", autospec=True, return_value=mock_tcp_socket)

    @pytest.fixture
    @staticmethod
    def mock_stream_data_consumer(mocker: MockerFixture) -> MagicMock:
        return mocker.NonCallableMagicMock(spec=StreamDataConsumer)

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_stream_data_consumer_cls(mocker: MockerFixture, mock_stream_data_consumer: MagicMock) -> MagicMock:
        return mocker.patch(
            "easynetwork.lowlevel._stream.StreamDataConsumer",
            return_value=mock_stream_data_consumer,
        )

    @pytest.fixture(autouse=True)
    @classmethod
    def local_address(
        cls,
        mock_tcp_socket: MagicMock,
        mock_ssl_socket: MagicMock,
        socket_family: int,
        global_local_address: tuple[str, int],
    ) -> tuple[str, int]:
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
        cls.set_remote_address_to_socket_mock(mock_tcp_socket, socket_family, global_remote_address)
        cls.set_remote_address_to_socket_mock(mock_ssl_socket, socket_family, global_remote_address)
        return global_remote_address

    @pytest.fixture  # DO NOT set autouse=True
    @staticmethod
    def setup_producer_mock(mock_stream_protocol: MagicMock) -> None:
        def generate_chunks_side_effect(packet: Any) -> Generator[bytes, None, None]:
            yield str(packet).removeprefix("sentinel.").encode("ascii") + b"\n"

        mock_stream_protocol.generate_chunks.side_effect = generate_chunks_side_effect

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

        def get_buffer_side_effect() -> memoryview:
            nonlocal bytes_buffer

            return memoryview(bytes_buffer)

        mock_stream_data_consumer.feed.side_effect = feed_side_effect
        mock_stream_data_consumer.__iter__.side_effect = lambda: mock_stream_data_consumer
        mock_stream_data_consumer.__next__.side_effect = next_side_effect
        mock_stream_data_consumer.get_buffer.side_effect = get_buffer_side_effect

    @pytest.fixture
    @staticmethod
    def max_recv_size(request: Any) -> int | None:
        return getattr(request, "param", None)

    @pytest.fixture
    @staticmethod
    def ssl_shutdown_timeout(request: Any) -> float | None:
        return getattr(request, "param", None)

    @pytest.fixture
    @staticmethod
    def ssl_shared_lock(request: Any) -> bool | None:
        return getattr(request, "param", None)

    @pytest.fixture
    @staticmethod
    def retry_interval(request: Any) -> float:
        return getattr(request, "param", float("+inf"))

    @pytest.fixture(params=["REMOTE_ADDRESS", "EXTERNAL_SOCKET"])
    @staticmethod
    def client(
        request: Any,
        max_recv_size: int | None,
        ssl_shutdown_timeout: float | None,
        retry_interval: float,
        remote_address: tuple[str, int],
        mock_tcp_socket: MagicMock,
        mock_ssl_socket: MagicMock,
        mock_stream_protocol: MagicMock,
        ssl_context: MagicMock | None,
        server_hostname: Any | None,
        ssl_shared_lock: bool | None,
        mock_selector_register: MagicMock,
        mock_selector_select: MagicMock,
    ) -> TCPNetworkClient[Any, Any]:
        try:
            match request.param:
                case "REMOTE_ADDRESS":
                    return TCPNetworkClient(
                        remote_address,
                        mock_stream_protocol,
                        ssl=ssl_context,
                        server_hostname=server_hostname,
                        max_recv_size=max_recv_size,
                        ssl_shutdown_timeout=ssl_shutdown_timeout,
                        ssl_shared_lock=ssl_shared_lock,
                        retry_interval=retry_interval,
                    )
                case "EXTERNAL_SOCKET":
                    return TCPNetworkClient(
                        mock_tcp_socket,
                        mock_stream_protocol,
                        ssl=ssl_context,
                        server_hostname=server_hostname,
                        max_recv_size=max_recv_size,
                        ssl_shutdown_timeout=ssl_shutdown_timeout,
                        ssl_shared_lock=ssl_shared_lock,
                        retry_interval=retry_interval,
                    )
                case invalid:
                    pytest.fail(f"Invalid fixture param: Got {invalid!r}")
        finally:
            mock_tcp_socket.reset_mock()
            mock_ssl_socket.reset_mock()
            mock_selector_register.reset_mock()
            mock_selector_select.reset_mock()

    @pytest.fixture(
        params=[
            pytest.param(None, id="blocking (None)"),
            pytest.param(float("+inf"), id="blocking (+inf)"),
            pytest.param(0, id="non_blocking"),
            pytest.param(123456789, id="with_timeout"),
        ]
    )
    @staticmethod
    def recv_timeout(request: Any) -> Any:
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
    def send_timeout(request: Any) -> Any:
        return request.param

    def test____dunder_init____connect_to_remote(
        self,
        remote_address: tuple[str, int],
        mock_tcp_socket: MagicMock,
        mock_socket_create_connection: MagicMock,
        mock_stream_data_consumer_cls: MagicMock,
        mock_stream_protocol: MagicMock,
        ssl_context: MagicMock | None,
        server_hostname: Any | None,
        mock_ssl_context: MagicMock,
        mock_ssl_create_default_context: MagicMock,
        mock_ssl_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        _ = TCPNetworkClient(
            remote_address,
            ssl=ssl_context,
            server_hostname=server_hostname,
            protocol=mock_stream_protocol,
            connect_timeout=mocker.sentinel.timeout,
            local_address=mocker.sentinel.local_address,
        )

        # Assert
        mock_stream_data_consumer_cls.assert_called_once_with(mock_stream_protocol)
        mock_socket_create_connection.assert_called_once_with(
            remote_address,
            timeout=mocker.sentinel.timeout,
            source_address=mocker.sentinel.local_address,
            all_errors=True,
        )
        mock_ssl_create_default_context.assert_not_called()
        if ssl_context:
            mock_ssl_context.wrap_socket.assert_called_once_with(
                mock_tcp_socket,
                server_side=False,
                do_handshake_on_connect=False,
                suppress_ragged_eofs=False,
                server_hostname=server_hostname,
                session=None,
            )
            mock_ssl_socket.do_handshake.assert_called_once_with()
        else:
            mock_ssl_context.wrap_socket.assert_not_called()
            mock_ssl_socket.do_handshake.assert_not_called()

        if ssl_context:
            assert mock_ssl_socket.mock_calls == [
                mocker.call.setblocking(False),
                mocker.call.do_handshake(),
                mocker.call.setsockopt(IPPROTO_TCP, TCP_NODELAY, True),
                mocker.call.setsockopt(SOL_SOCKET, SO_KEEPALIVE, True),
            ]
            assert mock_tcp_socket.mock_calls == [
                mocker.call.getpeername(),
                mocker.call.detach(),
            ]
        else:
            assert mock_tcp_socket.mock_calls == [
                mocker.call.getpeername(),
                mocker.call.setblocking(False),
                mocker.call.setsockopt(IPPROTO_TCP, TCP_NODELAY, True),
                mocker.call.setsockopt(SOL_SOCKET, SO_KEEPALIVE, True),
            ]
            assert mock_ssl_context.mock_calls == []

    def test____dunder_init____use_given_socket(
        self,
        mock_tcp_socket: MagicMock,
        mock_socket_create_connection: MagicMock,
        mock_stream_data_consumer_cls: MagicMock,
        mock_stream_protocol: MagicMock,
        ssl_context: MagicMock | None,
        server_hostname: Any | None,
        mock_ssl_context: MagicMock,
        mock_ssl_socket: MagicMock,
        mock_ssl_create_default_context: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        _ = TCPNetworkClient(
            mock_tcp_socket,
            protocol=mock_stream_protocol,
            ssl=ssl_context,
            server_hostname=server_hostname,
        )

        # Assert
        mock_stream_data_consumer_cls.assert_called_once_with(mock_stream_protocol)
        mock_socket_create_connection.assert_not_called()
        mock_ssl_create_default_context.assert_not_called()
        if ssl_context:
            mock_ssl_context.wrap_socket.assert_called_once_with(
                mock_tcp_socket,
                server_side=False,
                do_handshake_on_connect=False,
                suppress_ragged_eofs=False,
                server_hostname=server_hostname,
                session=None,
            )
            mock_ssl_socket.do_handshake.assert_called_once_with()
        else:
            mock_ssl_context.wrap_socket.assert_not_called()
            mock_ssl_socket.do_handshake.assert_not_called()

        if ssl_context:
            assert mock_ssl_socket.mock_calls == [
                mocker.call.setblocking(False),
                mocker.call.do_handshake(),
                mocker.call.setsockopt(IPPROTO_TCP, TCP_NODELAY, True),
                mocker.call.setsockopt(SOL_SOCKET, SO_KEEPALIVE, True),
            ]
            assert mock_tcp_socket.mock_calls == [
                mocker.call.getpeername(),
                mocker.call.detach(),
            ]
        else:
            assert mock_tcp_socket.mock_calls == [
                mocker.call.getpeername(),
                mocker.call.setblocking(False),
                mocker.call.setsockopt(IPPROTO_TCP, TCP_NODELAY, True),
                mocker.call.setsockopt(SOL_SOCKET, SO_KEEPALIVE, True),
            ]
            assert mock_ssl_context.mock_calls == []

    @pytest.mark.parametrize("socket_family", list(UNSUPPORTED_FAMILIES), indirect=True)
    def test____dunder_init____use_given_socket____invalid_socket_family(
        self,
        mock_tcp_socket: MagicMock,
        mock_stream_protocol: MagicMock,
        ssl_context: MagicMock | None,
        server_hostname: Any | None,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^Only these families are supported: .+$"):
            _ = TCPNetworkClient(
                mock_tcp_socket,
                protocol=mock_stream_protocol,
                ssl=ssl_context,
                server_hostname=server_hostname,
            )

    def test____dunder_init____invalid_socket_type_error(
        self,
        mock_udp_socket: MagicMock,
        mock_socket_create_connection: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_ssl_create_default_context: MagicMock,
        ssl_context: MagicMock | None,
        server_hostname: Any | None,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        with pytest.raises(ValueError, match=r"^A 'SOCK_STREAM' socket is expected$"):
            _ = TCPNetworkClient(
                mock_udp_socket,
                protocol=mock_stream_protocol,
                ssl=ssl_context,
                server_hostname=server_hostname,
            )

        # Assert
        mock_socket_create_connection.assert_not_called()
        mock_ssl_create_default_context.assert_not_called()
        if ssl_context:
            ssl_context.wrap_socket.assert_not_called()
        assert mock_udp_socket.mock_calls == [mocker.call.getpeername(), mocker.call.close()]

    def test____dunder_init____socket_given_is_not_connected_error(
        self,
        mock_tcp_socket: MagicMock,
        mock_socket_create_connection: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_ssl_create_default_context: MagicMock,
        ssl_context: MagicMock | None,
        server_hostname: Any | None,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        enotconn_exception = self.configure_socket_mock_to_raise_ENOTCONN(mock_tcp_socket)

        # Act
        with pytest.raises(OSError) as exc_info:
            _ = TCPNetworkClient(
                mock_tcp_socket,
                protocol=mock_stream_protocol,
                ssl=ssl_context,
                server_hostname=server_hostname,
            )

        # Assert
        assert exc_info.value.errno == enotconn_exception.errno
        mock_socket_create_connection.assert_not_called()
        mock_ssl_create_default_context.assert_not_called()
        if ssl_context:
            ssl_context.wrap_socket.assert_not_called()
        assert mock_tcp_socket.mock_calls == [mocker.call.getpeername(), mocker.call.close()]

    @pytest.mark.parametrize("use_socket", [False, True], ids=lambda p: f"use_socket=={p}")
    def test____dunder_init____protocol____invalid_value(
        self,
        use_socket: bool,
        remote_address: tuple[str, int],
        mock_tcp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        ssl_context: MagicMock | None,
        mock_ssl_socket: MagicMock,
        server_hostname: Any | None,
    ) -> None:
        # Arrange

        # Act
        with pytest.raises(TypeError, match=r"^Expected a StreamProtocol object, got .*$"):
            if use_socket:
                _ = TCPNetworkClient(
                    mock_tcp_socket,
                    protocol=mock_datagram_protocol,
                    ssl=ssl_context,
                    server_hostname=server_hostname,
                )
            else:
                _ = TCPNetworkClient(
                    remote_address,
                    protocol=mock_datagram_protocol,
                    ssl=ssl_context,
                    server_hostname=server_hostname,
                )

        # Assert
        if ssl_context:
            mock_ssl_socket.close.assert_called_once()
            mock_tcp_socket.close.assert_not_called()
        else:
            mock_tcp_socket.close.assert_called_once()
            mock_ssl_socket.close.assert_not_called()

    @pytest.mark.parametrize("max_recv_size", [None, 1, 2**64], ids=lambda p: f"max_recv_size=={p}")
    @pytest.mark.parametrize("use_socket", [False, True], ids=lambda p: f"use_socket=={p}")
    def test____dunder_init____max_size____valid_value(
        self,
        max_recv_size: int | None,
        use_socket: bool,
        remote_address: tuple[str, int],
        mock_tcp_socket: MagicMock,
        mock_stream_protocol: MagicMock,
        ssl_context: MagicMock | None,
        server_hostname: Any | None,
    ) -> None:
        # Arrange
        expected_size: int = max_recv_size if max_recv_size is not None else DEFAULT_STREAM_BUFSIZE

        # Act
        client: TCPNetworkClient[Any, Any]
        if use_socket:
            client = TCPNetworkClient(
                mock_tcp_socket,
                protocol=mock_stream_protocol,
                max_recv_size=max_recv_size,
                ssl=ssl_context,
                server_hostname=server_hostname,
            )
        else:
            client = TCPNetworkClient(
                remote_address,
                protocol=mock_stream_protocol,
                max_recv_size=max_recv_size,
                ssl=ssl_context,
                server_hostname=server_hostname,
            )

        # Assert
        assert client.max_recv_size == expected_size

    @pytest.mark.parametrize("max_recv_size", [0, -1, 10.4], ids=lambda p: f"max_recv_size=={p}")
    @pytest.mark.parametrize("use_socket", [False, True], ids=lambda p: f"use_socket=={p}")
    def test____dunder_init____max_size____invalid_value(
        self,
        max_recv_size: Any,
        use_socket: bool,
        remote_address: tuple[str, int],
        mock_tcp_socket: MagicMock,
        mock_stream_protocol: MagicMock,
        ssl_context: MagicMock | None,
        server_hostname: Any | None,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^'max_recv_size' must be a strictly positive integer$"):
            if use_socket:
                _ = TCPNetworkClient(
                    mock_tcp_socket,
                    protocol=mock_stream_protocol,
                    max_recv_size=max_recv_size,
                    ssl=ssl_context,
                    server_hostname=server_hostname,
                )
            else:
                _ = TCPNetworkClient(
                    remote_address,
                    protocol=mock_stream_protocol,
                    max_recv_size=max_recv_size,
                    ssl=ssl_context,
                    server_hostname=server_hostname,
                )

    @pytest.mark.parametrize("retry_interval", [0, -12.34])
    @pytest.mark.parametrize("use_socket", [False, True], ids=lambda p: f"use_socket=={p}")
    def test____dunder_init____retry_interval____invalid_value(
        self,
        retry_interval: float,
        use_socket: bool,
        remote_address: tuple[str, int],
        mock_tcp_socket: MagicMock,
        mock_stream_protocol: MagicMock,
        ssl_context: MagicMock | None,
        server_hostname: Any | None,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^retry_interval must be a strictly positive float$"):
            if use_socket:
                _ = TCPNetworkClient(
                    mock_tcp_socket,
                    protocol=mock_stream_protocol,
                    retry_interval=retry_interval,
                    ssl=ssl_context,
                    server_hostname=server_hostname,
                )
            else:
                _ = TCPNetworkClient(
                    remote_address,
                    protocol=mock_stream_protocol,
                    retry_interval=retry_interval,
                    ssl=ssl_context,
                    server_hostname=server_hostname,
                )

    @pytest.mark.parametrize("use_ssl", ["NO_SSL"], indirect=True)
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

    @pytest.mark.parametrize("use_ssl", ["USE_SSL"], indirect=True)
    def test____dunder_init____ssl____server_hostname____use_remote_host_by_default(
        self,
        remote_address: tuple[str, int],
        mock_ssl_context: MagicMock,
        mock_tcp_socket: MagicMock,
        mock_stream_protocol: MagicMock,
    ) -> None:
        # Arrange
        remote_host, _ = remote_address

        # Act
        _ = TCPNetworkClient(
            remote_address,
            protocol=mock_stream_protocol,
            ssl=mock_ssl_context,
            server_hostname=None,
        )

        # Assert
        mock_ssl_context.wrap_socket.assert_called_once_with(
            mock_tcp_socket,
            server_side=False,
            do_handshake_on_connect=False,
            suppress_ragged_eofs=False,
            server_hostname=remote_host,
            session=None,
        )

    @pytest.mark.parametrize("use_ssl", ["USE_SSL"], indirect=True)
    @pytest.mark.parametrize("use_socket", [False, True], ids=lambda p: f"use_socket=={p}")
    def test____dunder_init____ssl____server_hostname____do_not_disable_hostname_check_for_external_context(
        self,
        use_socket: bool,
        remote_address: tuple[str, int],
        mock_ssl_context: MagicMock,
        mock_tcp_socket: MagicMock,
        mock_stream_protocol: MagicMock,
    ) -> None:
        # Arrange
        assert mock_ssl_context.check_hostname

        # Act
        if use_socket:
            _ = TCPNetworkClient(
                mock_tcp_socket,
                protocol=mock_stream_protocol,
                ssl=mock_ssl_context,
                server_hostname="",
            )
        else:
            _ = TCPNetworkClient(
                remote_address,
                protocol=mock_stream_protocol,
                ssl=mock_ssl_context,
                server_hostname="",
            )

        # Assert
        assert mock_ssl_context.check_hostname is True
        mock_ssl_context.wrap_socket.assert_called_once_with(
            mock_tcp_socket,
            server_side=False,
            do_handshake_on_connect=False,
            suppress_ragged_eofs=False,
            server_hostname=None,
            session=None,
        )

    @pytest.mark.parametrize("use_ssl", ["USE_SSL"], indirect=True)
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
        _, remote_port = remote_address
        del remote_address

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
                    ("", remote_port),
                    protocol=mock_stream_protocol,
                    ssl=mock_ssl_context,
                    server_hostname=None,
                )

    @pytest.mark.parametrize("use_ssl", ["USE_SSL"], indirect=True)
    @pytest.mark.parametrize("use_socket", [False, True], ids=lambda p: f"use_socket=={p}")
    def test____dunder_init____ssl____create_default_context(
        self,
        use_socket: bool,
        remote_address: tuple[str, int],
        mock_ssl_context: MagicMock,
        mock_tcp_socket: MagicMock,
        mock_ssl_create_default_context: MagicMock,
        mock_stream_protocol: MagicMock,
        server_hostname: Any,
    ) -> None:
        # Arrange

        # Act
        if use_socket:
            _ = TCPNetworkClient(
                mock_tcp_socket,
                protocol=mock_stream_protocol,
                ssl=True,
                server_hostname=server_hostname,
            )
        else:
            _ = TCPNetworkClient(
                remote_address,
                protocol=mock_stream_protocol,
                ssl=True,
                server_hostname=server_hostname,
            )

        # Assert
        mock_ssl_create_default_context.assert_called_once_with()
        mock_ssl_context.wrap_socket.assert_called_once_with(
            mock_tcp_socket,
            server_side=False,
            do_handshake_on_connect=False,
            suppress_ragged_eofs=False,
            server_hostname=server_hostname,
            session=None,
        )

    @pytest.mark.parametrize("use_ssl", ["USE_SSL"], indirect=True)
    @pytest.mark.parametrize("use_socket", [False, True], ids=lambda p: f"use_socket=={p}")
    def test____dunder_init____ssl____create_default_context____disable_hostname_check(
        self,
        use_socket: bool,
        remote_address: tuple[str, int],
        mock_ssl_context: MagicMock,
        mock_tcp_socket: MagicMock,
        mock_ssl_create_default_context: MagicMock,
        mock_stream_protocol: MagicMock,
    ) -> None:
        # Arrange
        check_hostname_by_default: bool = mock_ssl_context.check_hostname
        assert check_hostname_by_default

        # Act
        if use_socket:
            _ = TCPNetworkClient(
                mock_tcp_socket,
                protocol=mock_stream_protocol,
                ssl=True,
                server_hostname="",
            )
        else:
            _ = TCPNetworkClient(
                remote_address,
                protocol=mock_stream_protocol,
                ssl=True,
                server_hostname="",
            )

        # Assert
        mock_ssl_create_default_context.assert_called_once_with()
        mock_ssl_context.wrap_socket.assert_called_once_with(
            mock_tcp_socket,
            server_side=False,
            do_handshake_on_connect=False,
            suppress_ragged_eofs=False,
            server_hostname=None,
            session=None,
        )
        assert mock_ssl_context.check_hostname is False

    @pytest.mark.parametrize("use_ssl", ["USE_SSL"], indirect=True)
    @pytest.mark.parametrize("use_socket", [False, True], ids=lambda p: f"use_socket=={p}")
    @pytest.mark.parametrize("ssl_handshake_timeout", [None, 0, 1234567.89], ids=lambda p: f"timeout=={p}")
    @pytest.mark.parametrize(
        ["would_block_exception", "would_block_event"],
        [
            pytest.param(SSLWantReadError, EVENT_READ, id="read"),
            pytest.param(SSLWantWriteError, EVENT_WRITE, id="write"),
        ],
    )
    def test____dunder_init____ssl____handshake_timeout(
        self,
        ssl_handshake_timeout: float | None,
        socket_fileno: int,
        use_socket: bool,
        retry_interval: float,
        would_block_exception: Exception,
        would_block_event: int,
        remote_address: tuple[str, int],
        mock_ssl_context: MagicMock,
        mock_tcp_socket: MagicMock,
        mock_ssl_socket: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_selector_register: MagicMock,
        mock_selector_select: MagicMock,
        server_hostname: Any,
    ) -> None:
        # Arrange
        expected_timeout: float = ssl_handshake_timeout if ssl_handshake_timeout is not None else SSL_HANDSHAKE_TIMEOUT
        mock_ssl_socket.do_handshake.side_effect = [would_block_exception, None]

        # Act
        with pytest.raises(TimeoutError) if expected_timeout == 0 else contextlib.nullcontext():
            if use_socket:
                _ = TCPNetworkClient(
                    mock_tcp_socket,
                    protocol=mock_stream_protocol,
                    ssl=mock_ssl_context,
                    server_hostname=server_hostname,
                    ssl_handshake_timeout=ssl_handshake_timeout,
                    retry_interval=retry_interval,
                )
            else:
                _ = TCPNetworkClient(
                    remote_address,
                    protocol=mock_stream_protocol,
                    ssl=mock_ssl_context,
                    server_hostname=server_hostname,
                    ssl_handshake_timeout=ssl_handshake_timeout,
                    retry_interval=retry_interval,
                )

        # Assert
        if expected_timeout == 0:
            assert len(mock_ssl_socket.do_handshake.call_args_list) == 1
            mock_selector_register.assert_not_called()
            mock_selector_select.assert_not_called()
        else:
            assert len(mock_ssl_socket.do_handshake.call_args_list) == 2
            mock_selector_register.assert_called_once_with(socket_fileno, would_block_event)
            mock_selector_select.assert_called_once_with(expected_timeout)

    def test____close____default(
        self,
        client: TCPNetworkClient[Any, Any],
        use_ssl: bool,
        mock_used_socket: MagicMock,
        mock_ssl_socket: MagicMock,
    ) -> None:
        # Arrange
        assert not client.is_closed()

        # Act
        client.close()

        # Assert
        assert client.is_closed()

        if use_ssl:
            mock_ssl_socket.unwrap.assert_called_once_with()

        mock_used_socket.shutdown.assert_called_once_with(SHUT_RDWR)
        mock_used_socket.close.assert_called_once_with()

    @pytest.mark.parametrize("use_ssl", ["USE_SSL"], indirect=True)
    @pytest.mark.parametrize("exception", [SSLEOFError, SSLZeroReturnError, ConnectionError])
    def test____close____ssl____connection_error_at_shutdown(
        self,
        client: TCPNetworkClient[Any, Any],
        exception: type[Exception],
        mock_ssl_socket: MagicMock,
    ) -> None:
        # Arrange
        assert not client.is_closed()
        mock_ssl_socket.unwrap.side_effect = exception

        # Act
        client.close()

        # Assert
        assert client.is_closed()

        mock_ssl_socket.unwrap.assert_called_once_with()

        mock_ssl_socket.shutdown.assert_called_once_with(SHUT_RDWR)
        mock_ssl_socket.close.assert_called_once_with()

    @pytest.mark.parametrize("use_ssl", ["USE_SSL"], indirect=True)
    def test____close____ssl____unrelated_ssl_error(
        self,
        client: TCPNetworkClient[Any, Any],
        mock_ssl_socket: MagicMock,
    ) -> None:
        # Arrange
        assert not client.is_closed()
        mock_ssl_socket.unwrap.side_effect = SSLError(SSLErrorNumber.SSL_ERROR_INVALID_ERROR_CODE, "SOMETHING")

        # Act
        client.close()

        # Assert
        assert client.is_closed()

        mock_ssl_socket.unwrap.assert_called_once_with()

        mock_ssl_socket.shutdown.assert_called_once_with(SHUT_RDWR)
        mock_ssl_socket.close.assert_called_once_with()

    @pytest.mark.parametrize("use_ssl", ["USE_SSL"], indirect=True)
    @pytest.mark.parametrize("ssl_shutdown_timeout", [None, 0, 1234567.89], ids=lambda p: f"timeout=={p}", indirect=True)
    @pytest.mark.parametrize(
        ["would_block_exception", "would_block_event"],
        [
            pytest.param(SSLWantReadError, EVENT_READ, id="read"),
            pytest.param(SSLWantWriteError, EVENT_WRITE, id="write"),
        ],
    )
    def test____close____ssl____shutdown_timeout(
        self,
        ssl_shutdown_timeout: float | None,
        socket_fileno: int,
        client: TCPNetworkClient[Any, Any],
        would_block_exception: Exception,
        would_block_event: int,
        mock_ssl_socket: MagicMock,
        mock_selector_register: MagicMock,
        mock_selector_select: MagicMock,
    ) -> None:
        # Arrange
        expected_timeout: float = ssl_shutdown_timeout if ssl_shutdown_timeout is not None else SSL_SHUTDOWN_TIMEOUT
        mock_ssl_socket.unwrap.side_effect = [would_block_exception, mock_ssl_socket]

        # Act
        client.close()

        # Assert
        assert client.is_closed()

        if expected_timeout == 0:
            assert mock_ssl_socket.unwrap.call_count == 1
            mock_ssl_socket.unwrap.assert_called_once()
            mock_selector_register.assert_not_called()
            mock_selector_select.assert_not_called()
        else:
            assert mock_ssl_socket.unwrap.call_count == 2
            mock_selector_register.assert_called_once_with(socket_fileno, would_block_event)
            mock_selector_select.assert_called_once_with(expected_timeout)

        mock_ssl_socket.shutdown.assert_called_once_with(SHUT_RDWR)
        mock_ssl_socket.close.assert_called_once_with()

    def test____close____shutdown_raises_OSError(
        self,
        client: TCPNetworkClient[Any, Any],
        mock_used_socket: MagicMock,
    ) -> None:
        # Arrange
        assert not client.is_closed()
        mock_used_socket.shutdown.side_effect = OSError()

        # Act
        client.close()

        # Assert
        assert client.is_closed()

        mock_used_socket.shutdown.assert_called_once_with(SHUT_RDWR)
        mock_used_socket.close.assert_called_once_with()

    def test____get_local_address____ask_for_address(
        self,
        client: TCPNetworkClient[Any, Any],
        socket_family: int,
        local_address: tuple[str, int],
        mock_used_socket: MagicMock,
    ) -> None:
        # Arrange

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
        socket_fileno: int,
        mock_used_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        fd = client.fileno()

        # Assert
        mock_used_socket.fileno.assert_called_once_with()
        assert fd == socket_fileno

    def test____fileno____closed_client(
        self,
        client: TCPNetworkClient[Any, Any],
        mock_used_socket: MagicMock,
    ) -> None:
        # Arrange
        client.close()
        assert client.is_closed()
        mock_used_socket.fileno.reset_mock()

        # Act
        fd = client.fileno()

        # Assert
        mock_used_socket.fileno.assert_called_once_with()
        assert fd == -1

    @pytest.mark.usefixtures("setup_producer_mock")
    def test____send_packet____send_bytes_to_socket(
        self,
        client: TCPNetworkClient[Any, Any],
        send_timeout: float | None,
        mock_used_socket: MagicMock,
        mock_used_socket_send: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_selector_select: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from socket import SO_ERROR, SOL_SOCKET

        # Act
        client.send_packet(mocker.sentinel.packet, timeout=send_timeout)

        # Assert
        mock_used_socket.settimeout.assert_not_called()
        mock_used_socket.setblocking.assert_not_called()
        mock_selector_select.assert_not_called()
        mock_stream_protocol.generate_chunks.assert_called_once_with(mocker.sentinel.packet)
        mock_used_socket_send.assert_called_once_with(b"packet\n")
        mock_used_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_ERROR)

    @pytest.mark.usefixtures("setup_producer_mock")
    def test____send_packet____blocking_operation(
        self,
        client: TCPNetworkClient[Any, Any],
        socket_fileno: int,
        send_timeout: float | None,
        use_ssl: bool,
        mock_used_socket: MagicMock,
        mock_used_socket_send: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_selector_register: MagicMock,
        mock_selector_select: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from socket import SO_ERROR, SOL_SOCKET

        mock_used_socket_send.side_effect = [SSLWantWriteError if use_ssl else BlockingIOError, len(b"pack"), len(b"et\n")]

        # Act
        with pytest.raises(TimeoutError) if send_timeout == 0 else contextlib.nullcontext():
            client.send_packet(mocker.sentinel.packet, timeout=send_timeout)

        # Assert
        mock_used_socket.settimeout.assert_not_called()
        mock_used_socket.setblocking.assert_not_called()
        mock_stream_protocol.generate_chunks.assert_called_once_with(mocker.sentinel.packet)
        if send_timeout != 0:
            mock_selector_register.assert_called_with(socket_fileno, EVENT_WRITE)
            if send_timeout in (None, float("+inf")):
                mock_selector_select.assert_called_with()
            else:
                mock_selector_select.assert_called_with(send_timeout)
            assert mock_used_socket_send.call_args_list == [
                mocker.call(b"packet\n"),
                mocker.call(b"packet\n"),
                mocker.call(b"et\n"),
            ]
            mock_used_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_ERROR)
        else:
            mock_selector_register.assert_not_called()
            mock_selector_select.assert_not_called()
            assert mock_used_socket_send.call_args_list == [mocker.call(b"packet\n")]
            mock_used_socket.getsockopt.assert_not_called()

    @pytest.mark.usefixtures("setup_producer_mock")
    def test____send_packet____raise_error_saved_in_SO_ERROR_option(
        self,
        client: TCPNetworkClient[Any, Any],
        mock_used_socket: MagicMock,
        mock_used_socket_send: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_selector_select: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from errno import EBUSY
        from socket import SO_ERROR, SOL_SOCKET

        mock_used_socket.getsockopt.return_value = EBUSY

        # Act
        with pytest.raises(OSError) as exc_info:
            client.send_packet(mocker.sentinel.packet)

        # Assert
        assert exc_info.value.errno == EBUSY
        mock_used_socket.settimeout.assert_not_called()
        mock_used_socket.setblocking.assert_not_called()
        mock_selector_select.assert_not_called()
        mock_stream_protocol.generate_chunks.assert_called_once_with(mocker.sentinel.packet)
        mock_used_socket_send.assert_called_once_with(b"packet\n")
        mock_used_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_ERROR)

    @pytest.mark.usefixtures("setup_producer_mock")
    def test____send_packet____closed_client_error(
        self,
        client: TCPNetworkClient[Any, Any],
        mock_used_socket: MagicMock,
        mock_used_socket_send: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_selector_select: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        client.close()
        assert client.is_closed()

        # Act
        with pytest.raises(ClientClosedError):
            client.send_packet(mocker.sentinel.packet)

        # Assert
        mock_used_socket.settimeout.assert_not_called()
        mock_used_socket.setblocking.assert_not_called()
        mock_selector_select.assert_not_called()
        mock_stream_protocol.generate_chunks.assert_not_called()
        mock_used_socket_send.assert_not_called()
        mock_used_socket.getsockopt.assert_not_called()

    @pytest.mark.usefixtures("setup_producer_mock")
    @pytest.mark.parametrize("use_ssl", ["USE_SSL"], indirect=True)
    @pytest.mark.parametrize("ssl_eof_error", [SSLEOFError, SSLZeroReturnError])
    def test____send_packet____ssl____eof_error(
        self,
        client: TCPNetworkClient[Any, Any],
        ssl_eof_error: type[Exception],
        mock_used_socket: MagicMock,
        mock_used_socket_send: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_selector_select: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_used_socket_send.side_effect = ssl_eof_error

        # Act
        with pytest.raises(ConnectionAbortedError):
            client.send_packet(mocker.sentinel.packet)

        # Assert
        mock_used_socket.settimeout.assert_not_called()
        mock_used_socket.setblocking.assert_not_called()
        mock_selector_select.assert_not_called()
        mock_stream_protocol.generate_chunks.assert_called_once_with(mocker.sentinel.packet)
        mock_used_socket_send.assert_called_once_with(b"packet\n")
        mock_used_socket.getsockopt.assert_not_called()

    @pytest.mark.usefixtures("setup_producer_mock")
    def test____send_packet____convert_connection_errors(
        self,
        client: TCPNetworkClient[Any, Any],
        mock_used_socket: MagicMock,
        mock_used_socket_send: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_selector_select: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_used_socket_send.side_effect = ConnectionError

        # Act
        with pytest.raises(ConnectionAbortedError):
            client.send_packet(mocker.sentinel.packet)

        # Assert
        mock_used_socket.settimeout.assert_not_called()
        mock_used_socket.setblocking.assert_not_called()
        mock_selector_select.assert_not_called()
        mock_stream_protocol.generate_chunks.assert_called_once_with(mocker.sentinel.packet)
        mock_used_socket_send.assert_called_once_with(b"packet\n")
        mock_used_socket.getsockopt.assert_not_called()

    @pytest.mark.usefixtures("setup_producer_mock")
    @pytest.mark.parametrize("closed_socket_errno", sorted(CLOSED_SOCKET_ERRNOS), ids=errno.errorcode.__getitem__)
    def test____send_packet____convert_closed_socket_errors(
        self,
        closed_socket_errno: int,
        client: TCPNetworkClient[Any, Any],
        mock_used_socket: MagicMock,
        mock_used_socket_send: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_selector_select: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_used_socket_send.side_effect = OSError(closed_socket_errno, os.strerror(closed_socket_errno))

        # Act
        with pytest.raises(ClientClosedError):
            client.send_packet(mocker.sentinel.packet)

        # Assert
        mock_used_socket.settimeout.assert_not_called()
        mock_used_socket.setblocking.assert_not_called()
        mock_selector_select.assert_not_called()
        mock_stream_protocol.generate_chunks.assert_called_once_with(mocker.sentinel.packet)
        mock_used_socket_send.assert_called_once_with(b"packet\n")
        mock_used_socket.getsockopt.assert_not_called()

    @pytest.mark.usefixtures("setup_producer_mock")
    @pytest.mark.parametrize("use_ssl", ["USE_SSL"], indirect=True)
    def test____send_packet____ssl____unrelated_ssl_error(
        self,
        client: TCPNetworkClient[Any, Any],
        mock_used_socket: MagicMock,
        mock_used_socket_send: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_selector_select: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_used_socket_send.side_effect = SSLError(SSLErrorNumber.SSL_ERROR_INVALID_ERROR_CODE, "SOMETHING")

        # Act
        with pytest.raises(SSLError) as exc_info:
            client.send_packet(mocker.sentinel.packet)

        # Assert
        assert exc_info.value is mock_used_socket_send.side_effect
        mock_used_socket.settimeout.assert_not_called()
        mock_used_socket.setblocking.assert_not_called()
        mock_selector_select.assert_not_called()
        mock_stream_protocol.generate_chunks.assert_called_once_with(mocker.sentinel.packet)
        mock_used_socket_send.assert_called_once_with(b"packet\n")
        mock_used_socket.getsockopt.assert_not_called()

    @pytest.mark.usefixtures("setup_producer_mock")
    @pytest.mark.parametrize("use_ssl", ["NO_SSL"], indirect=True)
    def test____send_eof____shutdown_socket(
        self,
        client: TCPNetworkClient[Any, Any],
        mock_used_socket: MagicMock,
        mock_used_socket_send: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_used_socket.shutdown.return_value = None

        # Act
        client.send_eof()

        # Assert
        mock_used_socket.shutdown.assert_called_once_with(SHUT_WR)
        with pytest.raises(RuntimeError, match=r"^send_eof\(\) has been called earlier$"):
            client.send_packet(mocker.sentinel.packet)
        mock_stream_protocol.generate_chunks.assert_not_called()
        mock_used_socket_send.assert_not_called()

    @pytest.mark.usefixtures("setup_producer_mock")
    @pytest.mark.parametrize("use_ssl", ["NO_SSL"], indirect=True)
    def test____send_eof____closed_client(
        self,
        client: TCPNetworkClient[Any, Any],
        mock_used_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_used_socket.shutdown.return_value = None
        client.close()
        mock_used_socket.shutdown.reset_mock()  # client.close() does socket.shutdown(SHUT_RDWR)

        # Act
        client.send_eof()

        # Assert
        mock_used_socket.shutdown.assert_not_called()

    @pytest.mark.usefixtures("setup_producer_mock")
    @pytest.mark.parametrize("use_ssl", ["NO_SSL"], indirect=True)
    def test____send_eof____idempotent(
        self,
        client: TCPNetworkClient[Any, Any],
        mock_used_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_used_socket.shutdown.return_value = None
        client.send_eof()

        # Act
        client.send_eof()

        # Assert
        mock_used_socket.shutdown.assert_called_once_with(SHUT_WR)

    @pytest.mark.usefixtures("setup_producer_mock")
    @pytest.mark.parametrize("use_ssl", ["USE_SSL"], indirect=True)
    def test____send_eof____ssl____operation_not_supported(
        self,
        client: TCPNetworkClient[Any, Any],
        mock_used_socket: MagicMock,
        mock_used_socket_send: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_used_socket.shutdown.return_value = None

        # Act
        with pytest.raises(NotImplementedError):
            client.send_eof()

        # Assert
        mock_used_socket.shutdown.assert_not_called()
        client.send_packet(mocker.sentinel.packet)
        mock_stream_protocol.generate_chunks.assert_called()
        mock_used_socket_send.assert_called()

    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____recv_packet____blocking_or_not____receive_bytes_from_socket(
        self,
        client: TCPNetworkClient[Any, Any],
        recv_timeout: float | None,
        mock_used_socket: MagicMock,
        mock_stream_data_consumer: MagicMock,
        mock_selector_register: MagicMock,
        mock_selector_select: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_used_socket.recv.side_effect = [b"packet\n"]

        # Act
        packet: Any = client.recv_packet(timeout=recv_timeout)

        # Assert
        mock_used_socket.settimeout.assert_not_called()
        mock_used_socket.setblocking.assert_not_called()

        mock_selector_register.assert_not_called()
        mock_selector_select.assert_not_called()

        mock_used_socket.recv.assert_called_once_with(DEFAULT_STREAM_BUFSIZE)
        mock_stream_data_consumer.feed.assert_called_once_with(b"packet\n")
        assert packet is mocker.sentinel.packet

    @pytest.mark.parametrize("recv_timeout", [None, float("+inf"), 123456789], indirect=True)  # Do not test with timeout==0
    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____recv_packet____blocking____partial_data(
        self,
        client: TCPNetworkClient[Any, Any],
        recv_timeout: float | None,
        mock_used_socket: MagicMock,
        mock_stream_data_consumer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_used_socket.recv.side_effect = [b"pac", b"ket\n"]

        # Act
        packet: Any = client.recv_packet(timeout=recv_timeout)

        # Assert
        mock_used_socket.settimeout.assert_not_called()
        mock_used_socket.setblocking.assert_not_called()
        assert mock_used_socket.recv.call_args_list == [mocker.call(DEFAULT_STREAM_BUFSIZE) for _ in range(2)]
        assert mock_stream_data_consumer.feed.call_args_list == [mocker.call(b"pac"), mocker.call(b"ket\n")]
        assert packet is mocker.sentinel.packet

    @pytest.mark.parametrize("recv_timeout", [0], indirect=True)  # Only test with timeout==0
    @pytest.mark.parametrize(
        "max_recv_size",
        [
            pytest.param(3, id="chunk_matching_bufsize"),
            pytest.param(1024, id="chunk_not_matching_bufsize"),
        ],
        indirect=True,
    )
    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____recv_packet____non_blocking____partial_data(
        self,
        client: TCPNetworkClient[Any, Any],
        max_recv_size: int,
        recv_timeout: float | None,
        mock_used_socket: MagicMock,
        mock_stream_data_consumer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_used_socket.recv.side_effect = [b"pac", b"ket", b"\n"]

        # Act & Assert
        if max_recv_size == 3:
            packet: Any = client.recv_packet(timeout=recv_timeout)

            assert mock_used_socket.recv.call_args_list == [mocker.call(max_recv_size) for _ in range(3)]
            assert mock_stream_data_consumer.feed.call_args_list == [mocker.call(b"pac"), mocker.call(b"ket"), mocker.call(b"\n")]
            assert packet is mocker.sentinel.packet
        else:
            with pytest.raises(TimeoutError):
                client.recv_packet(timeout=recv_timeout)

            mock_used_socket.recv.assert_called_once_with(max_recv_size)
            mock_stream_data_consumer.feed.assert_called_once_with(b"pac")

        mock_used_socket.settimeout.assert_not_called()
        mock_used_socket.setblocking.assert_not_called()

    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____recv_packet____blocking_or_not____extra_data(
        self,
        client: TCPNetworkClient[Any, Any],
        recv_timeout: float | None,
        mock_used_socket: MagicMock,
        mock_stream_data_consumer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_used_socket.recv.side_effect = [b"packet_1\npacket_2\n"]

        # Act
        packet_1: Any = client.recv_packet(timeout=recv_timeout)
        packet_2: Any = client.recv_packet(timeout=recv_timeout)

        # Assert
        mock_used_socket.recv.assert_called_once()
        mock_used_socket.settimeout.assert_not_called()
        mock_used_socket.setblocking.assert_not_called()
        mock_stream_data_consumer.feed.assert_called_once_with(b"packet_1\npacket_2\n")
        assert packet_1 is mocker.sentinel.packet_1
        assert packet_2 is mocker.sentinel.packet_2

    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____recv_packet____blocking_or_not____eof_error____default(
        self,
        client: TCPNetworkClient[Any, Any],
        recv_timeout: float | None,
        mock_used_socket: MagicMock,
        mock_stream_data_consumer: MagicMock,
    ) -> None:
        # Arrange
        mock_used_socket.recv.side_effect = [b""]

        # Act
        with pytest.raises(ConnectionAbortedError):
            _ = client.recv_packet(timeout=recv_timeout)

        # Assert
        mock_used_socket.settimeout.assert_not_called()
        mock_used_socket.setblocking.assert_not_called()
        mock_used_socket.recv.assert_called_once_with(DEFAULT_STREAM_BUFSIZE)
        mock_stream_data_consumer.feed.assert_not_called()

    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____recv_packet____blocking_or_not____eof_error____convert_connection_errors(
        self,
        client: TCPNetworkClient[Any, Any],
        recv_timeout: float | None,
        mock_used_socket: MagicMock,
        mock_stream_data_consumer: MagicMock,
    ) -> None:
        # Arrange
        mock_used_socket.recv.side_effect = ConnectionError

        # Act
        with pytest.raises(ConnectionAbortedError):
            _ = client.recv_packet(timeout=recv_timeout)

        # Assert
        mock_used_socket.settimeout.assert_not_called()
        mock_used_socket.setblocking.assert_not_called()
        mock_used_socket.recv.assert_called_once_with(DEFAULT_STREAM_BUFSIZE)
        mock_stream_data_consumer.feed.assert_not_called()

    @pytest.mark.usefixtures("setup_consumer_mock")
    @pytest.mark.parametrize("closed_socket_errno", sorted(CLOSED_SOCKET_ERRNOS), ids=errno.errorcode.__getitem__)
    def test____recv_packet____blocking_or_not____eof_error____convert_closed_socket_errors(
        self,
        closed_socket_errno: int,
        client: TCPNetworkClient[Any, Any],
        recv_timeout: float | None,
        mock_used_socket: MagicMock,
        mock_stream_data_consumer: MagicMock,
    ) -> None:
        # Arrange
        mock_used_socket.recv.side_effect = OSError(closed_socket_errno, os.strerror(closed_socket_errno))

        # Act
        with pytest.raises(ClientClosedError):
            _ = client.recv_packet(timeout=recv_timeout)

        # Assert
        mock_used_socket.settimeout.assert_not_called()
        mock_used_socket.setblocking.assert_not_called()
        mock_used_socket.recv.assert_called_once_with(DEFAULT_STREAM_BUFSIZE)
        mock_stream_data_consumer.feed.assert_not_called()

    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____recv_packet____blocking_or_not____protocol_parse_error(
        self,
        client: TCPNetworkClient[Any, Any],
        recv_timeout: float | None,
        mock_used_socket: MagicMock,
        mock_stream_data_consumer: MagicMock,
    ) -> None:
        # Arrange
        from easynetwork.exceptions import StreamProtocolParseError

        mock_used_socket.recv.side_effect = [b"packet\n"]
        expected_error = StreamProtocolParseError(b"", IncrementalDeserializeError("Sorry", b""))
        mock_stream_data_consumer.__next__.side_effect = [StopIteration, expected_error]

        # Act
        with pytest.raises(StreamProtocolParseError) as exc_info:
            _ = client.recv_packet(timeout=recv_timeout)
        exception = exc_info.value

        # Assert
        mock_used_socket.settimeout.assert_not_called()
        mock_used_socket.setblocking.assert_not_called()
        mock_used_socket.recv.assert_called_once_with(DEFAULT_STREAM_BUFSIZE)
        mock_stream_data_consumer.feed.assert_called_once_with(b"packet\n")
        assert exception is expected_error

    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____recv_packet____blocking_or_not____closed_client_error(
        self,
        client: TCPNetworkClient[Any, Any],
        recv_timeout: float | None,
        mock_used_socket: MagicMock,
        mock_selector_register: MagicMock,
        mock_selector_select: MagicMock,
        mock_stream_data_consumer: MagicMock,
    ) -> None:
        # Arrange
        client.close()
        assert client.is_closed()

        # Act
        with pytest.raises(ClientClosedError):
            _ = client.recv_packet(timeout=recv_timeout)

        # Assert
        mock_used_socket.settimeout.assert_not_called()
        mock_used_socket.setblocking.assert_not_called()
        mock_selector_register.assert_not_called()
        mock_selector_select.assert_not_called()
        mock_stream_data_consumer.feed.assert_not_called()
        mock_used_socket.recv.assert_not_called()

    @pytest.mark.usefixtures("setup_consumer_mock")
    @pytest.mark.parametrize("use_ssl", ["USE_SSL"], indirect=True)
    @pytest.mark.parametrize("ssl_eof_error", [SSLEOFError, SSLZeroReturnError])
    def test____recv_packet____blocking_or_not____ssl____eof_error(
        self,
        client: TCPNetworkClient[Any, Any],
        ssl_eof_error: type[Exception],
        recv_timeout: float | None,
        mock_used_socket: MagicMock,
        mock_stream_data_consumer: MagicMock,
    ) -> None:
        # Arrange
        mock_used_socket.recv.side_effect = ssl_eof_error

        # Act
        with pytest.raises(ConnectionAbortedError):
            _ = client.recv_packet(timeout=recv_timeout)

        # Assert
        mock_used_socket.settimeout.assert_not_called()
        mock_used_socket.setblocking.assert_not_called()
        mock_used_socket.recv.assert_called_once_with(DEFAULT_STREAM_BUFSIZE)
        mock_stream_data_consumer.feed.assert_not_called()

    @pytest.mark.usefixtures("setup_consumer_mock")
    @pytest.mark.parametrize("use_ssl", ["USE_SSL"], indirect=True)
    def test____recv_packet____blocking_or_not____ssl____unrelated_ssl_error(
        self,
        client: TCPNetworkClient[Any, Any],
        recv_timeout: float | None,
        mock_used_socket: MagicMock,
        mock_stream_data_consumer: MagicMock,
    ) -> None:
        # Arrange
        mock_used_socket.recv.side_effect = SSLError(SSLErrorNumber.SSL_ERROR_INVALID_ERROR_CODE, "SOMETHING")

        # Act
        with pytest.raises(SSLError) as exc_info:
            _ = client.recv_packet(timeout=recv_timeout)

        # Assert
        assert exc_info.value is mock_used_socket.recv.side_effect
        mock_used_socket.settimeout.assert_not_called()
        mock_used_socket.setblocking.assert_not_called()
        mock_used_socket.recv.assert_called_once_with(DEFAULT_STREAM_BUFSIZE)
        mock_stream_data_consumer.feed.assert_not_called()

    @pytest.mark.parametrize(
        "recv_timeout",
        [
            pytest.param(0, id="null timeout"),
            pytest.param(123456789, id="strictly positive timeout"),
        ],
    )
    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____recv_packet____timeout(
        self,
        client: TCPNetworkClient[Any, Any],
        use_ssl: bool,
        recv_timeout: int,
        socket_fileno: int,
        mock_used_socket: MagicMock,
        mock_selector_select: MagicMock,
        mock_selector_register: MagicMock,
        mock_stream_data_consumer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_used_socket.recv.side_effect = SSLWantReadError if use_ssl else BlockingIOError
        self.selector_timeout_after_n_calls(mock_selector_select, mocker, nb_calls=1)

        # Act & Assert
        with pytest.raises(TimeoutError):
            _ = client.recv_packet(timeout=recv_timeout)

        if recv_timeout == 0:
            assert len(mock_used_socket.recv.call_args_list) == 1
            mock_selector_register.assert_not_called()
            mock_selector_select.assert_not_called()
        else:
            assert len(mock_used_socket.recv.call_args_list) == 2
            mock_selector_register.assert_called_with(socket_fileno, EVENT_READ)
            mock_selector_select.assert_any_call(recv_timeout)
        mock_stream_data_consumer.feed.assert_not_called()

    @pytest.mark.parametrize(
        "recv_timeout",
        [
            pytest.param(0, id="null timeout"),
            pytest.param(123456789, id="strictly positive timeout"),
        ],
    )
    @pytest.mark.parametrize("max_recv_size", [3], indirect=True)  # Needed for timeout==0
    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____iter_received_packets____yields_available_packets_with_given_timeout(
        self,
        client: TCPNetworkClient[Any, Any],
        use_ssl: bool,
        max_recv_size: int,
        recv_timeout: int,
        mock_used_socket: MagicMock,
        mock_selector_select: MagicMock,
        mock_stream_data_consumer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_used_socket.recv.side_effect = [
            b"pac",
            b"ket",
            b"_1\np",
            b"ack",
            b"et_",
            b"2\n",
            SSLWantReadError if use_ssl else BlockingIOError,
        ]
        self.selector_timeout_after_n_calls(mock_selector_select, mocker, nb_calls=0)

        # Act
        packets = list(client.iter_received_packets(timeout=recv_timeout))

        # Assert
        assert mock_used_socket.recv.call_args_list == [mocker.call(max_recv_size) for _ in range(7)]
        assert mock_stream_data_consumer.feed.call_args_list == [
            mocker.call(b"pac"),
            mocker.call(b"ket"),
            mocker.call(b"_1\np"),
            mocker.call(b"ack"),
            mocker.call(b"et_"),
            mocker.call(b"2\n"),
        ]
        assert packets == [mocker.sentinel.packet_1, mocker.sentinel.packet_2]

    @pytest.mark.parametrize("max_recv_size", [3], indirect=True)  # Needed for timeout==0
    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____iter_received_packets____yields_available_packets_until_eof(
        self,
        client: TCPNetworkClient[Any, Any],
        max_recv_size: int,
        recv_timeout: float | None,
        mock_used_socket: MagicMock,
        mock_stream_data_consumer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_used_socket.recv.side_effect = [b"pac", b"ket", b"_1\np", b"ack", b"et_", b"2\n", b""]

        # Act
        packets = list(client.iter_received_packets(timeout=recv_timeout))

        # Assert
        assert mock_used_socket.recv.call_args_list == [mocker.call(max_recv_size) for _ in range(7)]
        assert mock_stream_data_consumer.feed.call_args_list == [
            mocker.call(b"pac"),
            mocker.call(b"ket"),
            mocker.call(b"_1\np"),
            mocker.call(b"ack"),
            mocker.call(b"et_"),
            mocker.call(b"2\n"),
        ]
        assert packets == [mocker.sentinel.packet_1, mocker.sentinel.packet_2]

    @pytest.mark.parametrize("max_recv_size", [3], indirect=True)  # Needed for timeout==0
    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____iter_received_packets____yields_available_packets_until_error(
        self,
        client: TCPNetworkClient[Any, Any],
        max_recv_size: int,
        recv_timeout: float | None,
        mock_used_socket: MagicMock,
        mock_stream_data_consumer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_used_socket.recv.side_effect = [b"pac", b"ket", b"_1\np", b"ack", b"et_", b"2\n", OSError]

        # Act
        packets = list(client.iter_received_packets(timeout=recv_timeout))

        # Assert
        assert mock_used_socket.recv.call_args_list == [mocker.call(max_recv_size) for _ in range(7)]
        assert mock_stream_data_consumer.feed.call_args_list == [
            mocker.call(b"pac"),
            mocker.call(b"ket"),
            mocker.call(b"_1\np"),
            mocker.call(b"ack"),
            mocker.call(b"et_"),
            mocker.call(b"2\n"),
        ]
        assert packets == [mocker.sentinel.packet_1, mocker.sentinel.packet_2]

    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____iter_received_packets____protocol_parse_error(
        self,
        client: TCPNetworkClient[Any, Any],
        recv_timeout: float | None,
        mock_stream_data_consumer: MagicMock,
    ) -> None:
        # Arrange
        from easynetwork.exceptions import StreamProtocolParseError

        mock_stream_data_consumer.__next__.side_effect = StreamProtocolParseError(b"", IncrementalDeserializeError("Sorry", b""))

        # Act
        with pytest.raises(StreamProtocolParseError) as exc_info:
            _ = next(client.iter_received_packets(timeout=recv_timeout))
        exception = exc_info.value

        # Assert
        assert exception is mock_stream_data_consumer.__next__.side_effect

    @pytest.mark.parametrize("several_generators", [False, True], ids=lambda t: f"several_generators=={t}")
    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____iter_received_packets____avoid_unnecessary_socket_recv_call(
        self,
        client: TCPNetworkClient[Any, Any],
        several_generators: bool,
        recv_timeout: float | None,
        mock_used_socket: MagicMock,
        mock_stream_data_consumer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_used_socket.recv.side_effect = [b"packet_1\npacket_2\n"]

        # Act
        if several_generators:
            packet_1 = next(client.iter_received_packets(timeout=recv_timeout))
            packet_2 = next(client.iter_received_packets(timeout=recv_timeout))
        else:
            iterator = client.iter_received_packets(timeout=recv_timeout)
            packet_1 = next(iterator)
            packet_2 = next(iterator)

        # Assert
        mock_used_socket.recv.assert_called_once_with(DEFAULT_STREAM_BUFSIZE)
        mock_stream_data_consumer.feed.assert_called_once_with(b"packet_1\npacket_2\n")
        assert packet_1 is mocker.sentinel.packet_1
        assert packet_2 is mocker.sentinel.packet_2

    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____iter_received_packets____closed_client_during_iteration(
        self,
        client: TCPNetworkClient[Any, Any],
        recv_timeout: float | None,
        mock_used_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_used_socket.recv.side_effect = [b"packet_1\n"]

        # Act & Assert
        iterator = client.iter_received_packets(timeout=recv_timeout)
        packet_1 = next(iterator)
        assert packet_1 is mocker.sentinel.packet_1
        client.close()
        assert client.is_closed()
        with pytest.raises(StopIteration):
            _ = next(iterator)

    @pytest.mark.usefixtures("setup_producer_mock", "setup_consumer_mock")
    def test____special_case____send_packet____eof_error____still_try_socket_send(
        self,
        client: TCPNetworkClient[Any, Any],
        mock_used_socket: MagicMock,
        mock_used_socket_send: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_used_socket.recv.side_effect = [b""]
        with pytest.raises(ConnectionAbortedError):
            _ = client.recv_packet()

        # Act
        client.send_packet(mocker.sentinel.packet)

        # Assert
        mock_stream_protocol.generate_chunks.assert_called_with(mocker.sentinel.packet)
        mock_used_socket.settimeout.assert_not_called()
        mock_used_socket_send.assert_called_with(b"packet\n")

    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____special_case____recv_packet____blocking_or_not____eof_error____do_not_try_socket_recv_on_next_call(
        self,
        client: TCPNetworkClient[Any, Any],
        recv_timeout: float | None,
        mock_used_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_used_socket.recv.side_effect = [b""]
        with pytest.raises(ConnectionAbortedError):
            _ = client.recv_packet(timeout=recv_timeout)

        mock_used_socket.recv.reset_mock()

        # Act
        with pytest.raises(ConnectionAbortedError):
            _ = client.recv_packet(timeout=recv_timeout)

        # Assert
        mock_used_socket.recv.assert_not_called()
        mock_used_socket.settimeout.assert_not_called()
        mock_used_socket.setblocking.assert_not_called()

    @pytest.mark.usefixtures("setup_producer_mock", "setup_consumer_mock")
    @pytest.mark.parametrize("use_ssl", ["NO_SSL"], indirect=True)
    def test____special_case____separate_send_and_receive_locks(
        self,
        client: TCPNetworkClient[Any, Any],
        mock_used_socket: MagicMock,
        mock_used_socket_send: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_selector_select: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def during_select() -> None:
            client.send_packet(mocker.sentinel.packet)

        mock_used_socket.recv.side_effect = [BlockingIOError, b""]
        self.selector_action_during_select(mock_selector_select, mocker, during_select)

        # Act
        with pytest.raises(ConnectionAbortedError):
            _ = client.recv_packet()

        # Assert
        mock_stream_protocol.generate_chunks.assert_called_with(mocker.sentinel.packet)
        mock_used_socket_send.assert_called_with(b"packet\n")

    @pytest.mark.usefixtures("setup_producer_mock", "setup_consumer_mock")
    @pytest.mark.parametrize("use_ssl", ["USE_SSL"], indirect=True)
    @pytest.mark.parametrize("ssl_shared_lock", [None, False, True], indirect=True, ids=lambda p: f"ssl_shared_lock=={p}")
    def test____special_case____separate_send_and_receive_locks____ssl(
        self,
        client: TCPNetworkClient[Any, Any],
        ssl_shared_lock: bool | None,
        mock_used_socket: MagicMock,
        mock_used_socket_send: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_selector_select: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        if ssl_shared_lock is None:
            ssl_shared_lock = True  # Should be true by default

        def during_select() -> None:
            with pytest.raises(DummyLock.WouldBlock) if ssl_shared_lock else contextlib.nullcontext():
                client.send_packet(mocker.sentinel.packet)

        mock_used_socket.recv.side_effect = [SSLWantReadError, b""]
        self.selector_action_during_select(mock_selector_select, mocker, during_select)

        # Act
        with pytest.raises(ConnectionAbortedError):
            _ = client.recv_packet()

        # Assert
        if ssl_shared_lock:
            mock_stream_protocol.generate_chunks.assert_not_called()
            mock_used_socket_send.assert_not_called()
        else:
            mock_stream_protocol.generate_chunks.assert_called_with(mocker.sentinel.packet)
            mock_used_socket_send.assert_called_with(b"packet\n")
