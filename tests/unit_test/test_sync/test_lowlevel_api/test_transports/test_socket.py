# mypy: disable-error-code=func-returns-value

from __future__ import annotations

import math
import ssl
from collections.abc import Callable
from socket import SHUT_RDWR, SHUT_WR
from typing import TYPE_CHECKING, Any

from easynetwork.api_sync.lowlevel.transports.base_selector import WouldBlockOnRead, WouldBlockOnWrite
from easynetwork.api_sync.lowlevel.transports.socket import (
    SocketAttribute,
    SocketDatagramTransport,
    SocketStreamTransport,
    SSLStreamTransport,
    TLSAttribute,
)
from easynetwork.tools.constants import MAX_DATAGRAM_BUFSIZE, SSL_HANDSHAKE_TIMEOUT
from easynetwork.tools.socket import SocketProxy

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class TestSocketStreamTransport:
    @pytest.fixture
    @staticmethod
    def socket_fileno(request: pytest.FixtureRequest) -> int:
        return getattr(request, "param", 12345)

    @pytest.fixture
    @staticmethod
    def mock_tcp_socket(mock_tcp_socket: MagicMock, socket_fileno: int) -> MagicMock:
        mock_tcp_socket.fileno.return_value = socket_fileno

        def close() -> None:
            mock_tcp_socket.fileno.return_value = -1

        mock_tcp_socket.close.side_effect = close

        mock_tcp_socket.getsockname.return_value = ("local_address", 11111)
        mock_tcp_socket.getpeername.return_value = ("remote_address", 12345)

        return mock_tcp_socket

    @pytest.fixture
    @staticmethod
    def transport(mock_tcp_socket: MagicMock) -> SocketStreamTransport:
        transport = SocketStreamTransport(mock_tcp_socket, math.inf)
        mock_tcp_socket.reset_mock()
        return transport

    def test____dunder_init____default(
        self,
        mock_tcp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_selector_factory = mocker.stub()

        # Act
        transport = SocketStreamTransport(mock_tcp_socket, math.inf, selector_factory=mock_selector_factory)

        # Assert
        assert transport._retry_interval is math.inf
        assert transport._selector_factory is mock_selector_factory
        assert isinstance(transport.extra(SocketAttribute.socket), SocketProxy)
        assert transport.extra(SocketAttribute.sockname) == ("local_address", 11111)
        assert transport.extra(SocketAttribute.peername) == ("remote_address", 12345)
        mock_tcp_socket.getsockname.assert_called_once_with()
        mock_tcp_socket.getpeername.assert_called_once_with()
        mock_tcp_socket.setblocking.assert_called_once_with(False)
        mock_tcp_socket.settimeout.assert_not_called()

    def test____dunder_init____forbid_ssl_sockets(
        self,
        mock_ssl_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^ssl\.SSLSocket instances are forbidden$"):
            _ = SocketStreamTransport(mock_ssl_socket, math.inf)

    def test____dunder_init____forbid_non_stream_sockets(
        self,
        mock_udp_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^A 'SOCK_STREAM' socket is expected$"):
            _ = SocketStreamTransport(mock_udp_socket, math.inf)

    @pytest.mark.parametrize(
        ["socket_fileno", "expected_state"],
        [
            pytest.param(0, False),
            pytest.param(12345, False),
            pytest.param(-1, True),
            pytest.param(-42, True),
        ],
        indirect=["socket_fileno"],
    )
    def test____is_closed____returned_state(
        self,
        expected_state: bool,
        transport: SocketStreamTransport,
    ) -> None:
        # Arrange

        # Act
        state = transport.is_closed()

        # Assert
        assert state is expected_state

    @pytest.mark.parametrize("error", [None, OSError])
    def test____close____default(
        self,
        error: type[OSError] | None,
        transport: SocketStreamTransport,
        mock_tcp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        if error is not None:
            mock_tcp_socket.shutdown.side_effect = error

        # Act
        transport.close()

        # Assert
        assert mock_tcp_socket.mock_calls == [mocker.call.shutdown(SHUT_RDWR), mocker.call.close()]

    def test____recv_noblock____default(
        self,
        transport: SocketStreamTransport,
        mock_tcp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_tcp_socket.recv.return_value = mocker.sentinel.bytes

        # Act
        result = transport.recv_noblock(mocker.sentinel.bufsize)

        # Assert
        mock_tcp_socket.recv.assert_called_once_with(mocker.sentinel.bufsize)
        mock_tcp_socket.fileno.assert_not_called()
        assert result is mocker.sentinel.bytes

    @pytest.mark.parametrize("error", [BlockingIOError, InterruptedError])
    def test____recv_noblock____blocking_error(
        self,
        error: type[OSError],
        transport: SocketStreamTransport,
        mock_tcp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_tcp_socket.recv.side_effect = error

        # Act
        with pytest.raises(WouldBlockOnRead) as exc_info:
            transport.recv_noblock(mocker.sentinel.bufsize)

        # Assert
        mock_tcp_socket.recv.assert_called_once_with(mocker.sentinel.bufsize)
        mock_tcp_socket.fileno.assert_called_once()
        assert exc_info.value.fileno is mock_tcp_socket.fileno.return_value

    def test____send_noblock____default(
        self,
        transport: SocketStreamTransport,
        mock_tcp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_tcp_socket.send.return_value = mocker.sentinel.nb_bytes_sent

        # Act
        result = transport.send_noblock(mocker.sentinel.data)

        # Assert
        mock_tcp_socket.send.assert_called_once_with(mocker.sentinel.data)
        mock_tcp_socket.fileno.assert_not_called()
        assert result is mocker.sentinel.nb_bytes_sent

    @pytest.mark.parametrize("error", [BlockingIOError, InterruptedError])
    def test____send_noblock____blocking_error(
        self,
        error: type[OSError],
        transport: SocketStreamTransport,
        mock_tcp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_tcp_socket.send.side_effect = error

        # Act
        with pytest.raises(WouldBlockOnWrite) as exc_info:
            transport.send_noblock(mocker.sentinel.data)

        # Assert
        mock_tcp_socket.send.assert_called_once_with(mocker.sentinel.data)
        mock_tcp_socket.fileno.assert_called_once()
        assert exc_info.value.fileno is mock_tcp_socket.fileno.return_value

    def test____send_eof____default(
        self,
        transport: SocketStreamTransport,
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act
        transport.send_eof()

        # Assert
        mock_tcp_socket.shutdown.assert_called_once_with(SHUT_WR)


def _retry_side_effect(callback: Callable[[], Any], timeout: float) -> Any:
    while True:
        try:
            return callback()
        except (WouldBlockOnRead, WouldBlockOnWrite):
            pass


class TestSSLStreamTransport:
    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_transport_retry(mocker: MockerFixture) -> MagicMock:
        mock_transport_retry = mocker.patch.object(SSLStreamTransport, "_retry")
        mock_transport_retry.side_effect = _retry_side_effect
        return mock_transport_retry

    @pytest.fixture
    @staticmethod
    def socket_fileno(request: pytest.FixtureRequest) -> int:
        return getattr(request, "param", 12345)

    @pytest.fixture
    @staticmethod
    def mock_ssl_socket(mock_ssl_socket: MagicMock, socket_fileno: int) -> MagicMock:
        mock_ssl_socket.fileno.return_value = socket_fileno

        def close() -> None:
            mock_ssl_socket.fileno.return_value = -1

        mock_ssl_socket.close.side_effect = close
        mock_ssl_socket.do_handshake.side_effect = [WouldBlockOnRead(socket_fileno), WouldBlockOnWrite(socket_fileno), None]
        mock_ssl_socket.unwrap.side_effect = [WouldBlockOnRead(socket_fileno), WouldBlockOnWrite(socket_fileno), None]

        mock_ssl_socket.getsockname.return_value = ("local_address", 11111)
        mock_ssl_socket.getpeername.return_value = ("remote_address", 12345)

        return mock_ssl_socket

    @pytest.fixture
    @staticmethod
    def mock_ssl_context(mock_ssl_context: MagicMock, mock_ssl_socket: MagicMock, mocker: MockerFixture) -> MagicMock:
        mock_ssl_context.wrap_socket.return_value = mock_ssl_socket
        mock_ssl_socket.context = mock_ssl_context
        mock_ssl_socket.getpeercert.return_value = mocker.sentinel.peercert
        mock_ssl_socket.cipher.return_value = mocker.sentinel.cipher
        mock_ssl_socket.compression.return_value = mocker.sentinel.compression
        mock_ssl_socket.version.return_value = mocker.sentinel.tls_version
        return mock_ssl_context

    @pytest.fixture
    @staticmethod
    def standard_compatible(request: pytest.FixtureRequest) -> bool:
        return getattr(request, "param", True)

    @pytest.fixture
    @staticmethod
    def transport(
        standard_compatible: bool,
        mock_tcp_socket: MagicMock,
        mock_ssl_socket: MagicMock,
        mock_ssl_context: MagicMock,
    ) -> SSLStreamTransport:
        transport = SSLStreamTransport(
            mock_tcp_socket,
            mock_ssl_context,
            handshake_timeout=123456789,
            shutdown_timeout=987654321,
            retry_interval=math.inf,
            standard_compatible=standard_compatible,
        )
        mock_tcp_socket.reset_mock()
        mock_ssl_socket.reset_mock()
        return transport

    def test____dunder_init____default(
        self,
        mock_tcp_socket: MagicMock,
        mock_ssl_socket: MagicMock,
        mock_ssl_context: MagicMock,
        mock_transport_retry: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_selector_factory = mocker.stub()

        # Act
        transport = SSLStreamTransport(
            mock_tcp_socket,
            mock_ssl_context,
            retry_interval=math.inf,
            server_hostname=mocker.sentinel.server_hostname,
            selector_factory=mock_selector_factory,
        )

        # Assert
        assert transport._retry_interval is math.inf
        assert transport._selector_factory is mock_selector_factory
        assert isinstance(transport.extra(SocketAttribute.socket), SocketProxy)
        assert transport.extra(SocketAttribute.sockname) == ("local_address", 11111)
        assert transport.extra(SocketAttribute.peername) == ("remote_address", 12345)
        assert transport.extra(TLSAttribute.sslcontext) is mock_ssl_context
        assert transport.extra(TLSAttribute.peercert) is mocker.sentinel.peercert
        assert transport.extra(TLSAttribute.cipher) is mocker.sentinel.cipher
        assert transport.extra(TLSAttribute.compression) is mocker.sentinel.compression
        assert transport.extra(TLSAttribute.tls_version) is mocker.sentinel.tls_version
        assert transport.extra(TLSAttribute.standard_compatible) is True
        assert mock_tcp_socket.mock_calls == []

        mock_ssl_context.wrap_socket.assert_called_once_with(
            mock_tcp_socket,
            server_side=False,
            server_hostname=mocker.sentinel.server_hostname,
            suppress_ragged_eofs=False,
            do_handshake_on_connect=False,
            session=None,
        )

        mock_ssl_socket.getsockname.assert_called_once_with()
        mock_ssl_socket.getpeername.assert_called_once_with()
        mock_ssl_socket.setblocking.assert_called_once_with(False)
        mock_ssl_socket.settimeout.assert_not_called()
        mock_transport_retry.assert_called_once_with(mocker.ANY, SSL_HANDSHAKE_TIMEOUT)
        assert mock_ssl_socket.do_handshake.call_args_list == [mocker.call() for _ in range(3)]

    @pytest.mark.parametrize("standard_compatible", [False, True], ids=lambda p: f"standard_compatible=={p}", indirect=True)
    def test____dunder_init____ssl_context_parameters(
        self,
        standard_compatible: bool,
        mock_tcp_socket: MagicMock,
        mock_ssl_context: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        transport = SSLStreamTransport(
            mock_tcp_socket,
            mock_ssl_context,
            handshake_timeout=123456789,
            shutdown_timeout=987654321,
            retry_interval=math.inf,
            server_side=mocker.sentinel.server_side,
            server_hostname=mocker.sentinel.server_hostname,
            standard_compatible=standard_compatible,
            session=mocker.sentinel.ssl_session,
        )

        # Assert
        mock_ssl_context.wrap_socket.assert_called_once_with(
            mock_tcp_socket,
            server_side=mocker.sentinel.server_side,
            server_hostname=mocker.sentinel.server_hostname,
            suppress_ragged_eofs=not standard_compatible,
            do_handshake_on_connect=False,
            session=mocker.sentinel.ssl_session,
        )
        assert transport.extra(TLSAttribute.standard_compatible) is standard_compatible

    def test____dunder_init____forbid_ssl_sockets(
        self,
        mock_ssl_socket: MagicMock,
        mock_ssl_context: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^ssl\.SSLSocket instances are forbidden$"):
            _ = SSLStreamTransport(mock_ssl_socket, mock_ssl_context, math.inf)

    def test____dunder_init____forbid_non_stream_sockets(
        self,
        mock_udp_socket: MagicMock,
        mock_ssl_context: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^A 'SOCK_STREAM' socket is expected$"):
            _ = SSLStreamTransport(mock_udp_socket, mock_ssl_context, math.inf)

    @pytest.mark.parametrize("timeout", [math.nan, -4], ids=repr)
    @pytest.mark.parametrize("parameter", ["handshake_timeout", "shutdown_timeout", "retry_interval"])
    def test____dunder_init____invalid_timeout(
        self,
        timeout: float,
        parameter: str,
        mock_tcp_socket: MagicMock,
        mock_ssl_context: MagicMock,
    ) -> None:
        # Arrange
        kwargs: dict[str, Any] = {
            "retry_interval": math.inf,
        }
        kwargs[parameter] = timeout

        # Act & Assert
        with pytest.raises(ValueError):
            _ = SSLStreamTransport(mock_tcp_socket, mock_ssl_context, **kwargs)

    def test____dunder_init____handshake_error(
        self,
        mock_tcp_socket: MagicMock,
        mock_ssl_socket: MagicMock,
        mock_ssl_context: MagicMock,
    ) -> None:
        # Arrange
        mock_ssl_socket.do_handshake.side_effect = ConnectionError

        # Act & Assert
        with pytest.raises(ConnectionError):
            _ = SSLStreamTransport(mock_tcp_socket, mock_ssl_context, math.inf)

        mock_ssl_socket.close.assert_called_once_with()

    @pytest.mark.usefixtures("simulate_no_ssl_module")
    def test____dunder_init____ssl_module_not_available(
        self,
        mock_tcp_socket: MagicMock,
        mock_ssl_context: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(RuntimeError, match=r"^stdlib ssl module not available$"):
            _ = SSLStreamTransport(mock_tcp_socket, mock_ssl_context, math.inf)

    @pytest.mark.parametrize(
        ["socket_fileno", "expected_state"],
        [
            pytest.param(0, False),
            pytest.param(12345, False),
            pytest.param(-1, True),
            pytest.param(-42, True),
        ],
        indirect=["socket_fileno"],
    )
    def test____is_closed____returned_state(
        self,
        expected_state: bool,
        transport: SSLStreamTransport,
    ) -> None:
        # Arrange

        # Act
        state = transport.is_closed()

        # Assert
        assert state is expected_state

    @pytest.mark.parametrize("unwrap_error", [None, OSError])
    @pytest.mark.parametrize("shutdown_error", [None, OSError])
    @pytest.mark.parametrize("standard_compatible", [False, True], ids=lambda p: f"standard_compatible=={p}", indirect=True)
    def test____close____default(
        self,
        standard_compatible: bool,
        socket_fileno: int,
        unwrap_error: type[OSError] | None,
        shutdown_error: type[OSError] | None,
        transport: SSLStreamTransport,
        mock_ssl_socket: MagicMock,
        mock_transport_retry: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        if unwrap_error is not None:
            mock_ssl_socket.unwrap.side_effect = [WouldBlockOnRead(socket_fileno), WouldBlockOnWrite(socket_fileno), unwrap_error]
        if shutdown_error is not None:
            mock_ssl_socket.shutdown.side_effect = shutdown_error
        mock_transport_retry.reset_mock()

        # Act
        transport.close()

        # Assert
        if standard_compatible:
            assert mock_ssl_socket.mock_calls == [
                mocker.call.unwrap(),
                mocker.call.unwrap(),
                mocker.call.unwrap(),
                mocker.call.shutdown(SHUT_RDWR),
                mocker.call.close(),
            ]
            mock_transport_retry.assert_called_once_with(mocker.ANY, 987654321)
        else:
            assert mock_ssl_socket.mock_calls == [
                mocker.call.shutdown(SHUT_RDWR),
                mocker.call.close(),
            ]
            mock_transport_retry.assert_not_called()

    def test____recv_noblock____default(
        self,
        transport: SSLStreamTransport,
        mock_ssl_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_ssl_socket.recv.return_value = mocker.sentinel.bytes

        # Act
        result = transport.recv_noblock(mocker.sentinel.bufsize)

        # Assert
        mock_ssl_socket.recv.assert_called_once_with(mocker.sentinel.bufsize)
        mock_ssl_socket.fileno.assert_not_called()
        assert result is mocker.sentinel.bytes

    @pytest.mark.parametrize(
        ["error", "expected_blocking_error"],
        [
            pytest.param(ssl.SSLWantReadError, WouldBlockOnRead),
            pytest.param(ssl.SSLSyscallError, WouldBlockOnRead),
            pytest.param(ssl.SSLWantWriteError, WouldBlockOnWrite),
        ],
    )
    def test____recv_noblock____blocking_error(
        self,
        error: type[OSError],
        expected_blocking_error: type[WouldBlockOnRead] | type[WouldBlockOnWrite],
        transport: SSLStreamTransport,
        mock_ssl_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_ssl_socket.recv.side_effect = error

        # Act
        with pytest.raises(expected_blocking_error) as exc_info:
            transport.recv_noblock(mocker.sentinel.bufsize)

        # Assert
        mock_ssl_socket.recv.assert_called_once_with(mocker.sentinel.bufsize)
        mock_ssl_socket.fileno.assert_called_once()
        assert isinstance(exc_info.value, (WouldBlockOnRead, WouldBlockOnWrite))
        assert exc_info.value.fileno is mock_ssl_socket.fileno.return_value

    def test____send_noblock____default(
        self,
        transport: SSLStreamTransport,
        mock_ssl_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_ssl_socket.send.return_value = mocker.sentinel.nb_bytes_sent

        # Act
        result = transport.send_noblock(mocker.sentinel.data)

        # Assert
        mock_ssl_socket.send.assert_called_once_with(mocker.sentinel.data)
        mock_ssl_socket.fileno.assert_not_called()
        assert result is mocker.sentinel.nb_bytes_sent

    @pytest.mark.parametrize(
        ["error", "expected_blocking_error"],
        [
            pytest.param(ssl.SSLWantReadError, WouldBlockOnRead),
            pytest.param(ssl.SSLSyscallError, WouldBlockOnRead),
            pytest.param(ssl.SSLWantWriteError, WouldBlockOnWrite),
        ],
    )
    def test____send_noblock____blocking_error(
        self,
        error: type[OSError],
        expected_blocking_error: type[WouldBlockOnRead] | type[WouldBlockOnWrite],
        transport: SSLStreamTransport,
        mock_ssl_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_ssl_socket.send.side_effect = error

        # Act
        with pytest.raises(expected_blocking_error) as exc_info:
            transport.send_noblock(mocker.sentinel.data)

        # Assert
        mock_ssl_socket.send.assert_called_once_with(mocker.sentinel.data)
        mock_ssl_socket.fileno.assert_called_once()
        assert isinstance(exc_info.value, (WouldBlockOnRead, WouldBlockOnWrite))
        assert exc_info.value.fileno is mock_ssl_socket.fileno.return_value

    def test____send_eof____default(
        self,
        transport: SocketStreamTransport,
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act
        with pytest.raises(NotImplementedError):
            transport.send_eof()

        # Assert
        mock_tcp_socket.shutdown.assert_not_called()


class TestSocketDatagramTransport:
    @pytest.fixture
    @staticmethod
    def socket_fileno(request: pytest.FixtureRequest) -> int:
        return getattr(request, "param", 12345)

    @pytest.fixture
    @staticmethod
    def mock_udp_socket(mock_udp_socket: MagicMock, socket_fileno: int) -> MagicMock:
        mock_udp_socket.fileno.return_value = socket_fileno

        def close() -> None:
            mock_udp_socket.fileno.return_value = -1

        mock_udp_socket.close.side_effect = close

        mock_udp_socket.getsockname.return_value = ("local_address", 11111)
        mock_udp_socket.getpeername.return_value = ("remote_address", 12345)

        return mock_udp_socket

    @pytest.fixture
    @staticmethod
    def max_datagram_size(request: pytest.FixtureRequest) -> int | None:
        return getattr(request, "param", None)

    @pytest.fixture
    @staticmethod
    def transport(mock_udp_socket: MagicMock, max_datagram_size: int | None) -> SocketDatagramTransport:
        if max_datagram_size is None:
            transport = SocketDatagramTransport(mock_udp_socket, math.inf)
        else:
            transport = SocketDatagramTransport(mock_udp_socket, math.inf, max_datagram_size=max_datagram_size)
        mock_udp_socket.reset_mock()
        return transport

    def test____dunder_init____default(
        self,
        mock_udp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_selector_factory = mocker.stub()

        # Act
        transport = SocketDatagramTransport(mock_udp_socket, math.inf, selector_factory=mock_selector_factory)

        # Assert
        assert transport._retry_interval is math.inf
        assert transport._selector_factory is mock_selector_factory
        assert isinstance(transport.extra(SocketAttribute.socket), SocketProxy)
        assert transport.extra(SocketAttribute.sockname) == ("local_address", 11111)
        assert transport.extra(SocketAttribute.peername) == ("remote_address", 12345)
        mock_udp_socket.getsockname.assert_called_once_with()
        mock_udp_socket.getpeername.assert_called_once_with()
        mock_udp_socket.setblocking.assert_called_once_with(False)
        mock_udp_socket.settimeout.assert_not_called()

    def test____dunder_init____forbid_ssl_sockets(
        self,
        mock_ssl_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^ssl\.SSLSocket instances are forbidden$"):
            _ = SocketDatagramTransport(mock_ssl_socket, math.inf)

    def test____dunder_init____forbid_non_datagram_sockets(
        self,
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^A 'SOCK_DGRAM' socket is expected$"):
            _ = SocketDatagramTransport(mock_tcp_socket, math.inf)

    @pytest.mark.parametrize("max_datagram_size", [0, -42], ids=lambda p: f"max_datagram_size=={p}")
    def test____dunder_init____invalid_datagram_size(
        self,
        max_datagram_size: int,
        mock_udp_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^max_datagram_size must not be <= 0$"):
            _ = SocketDatagramTransport(mock_udp_socket, math.inf, max_datagram_size=max_datagram_size)

    @pytest.mark.parametrize(
        ["socket_fileno", "expected_state"],
        [
            pytest.param(0, False),
            pytest.param(12345, False),
            pytest.param(-1, True),
            pytest.param(-42, True),
        ],
        indirect=["socket_fileno"],
    )
    def test____is_closed____returned_state(
        self,
        expected_state: bool,
        transport: SocketDatagramTransport,
    ) -> None:
        # Arrange

        # Act
        state = transport.is_closed()

        # Assert
        assert state is expected_state

    def test____close____default(
        self,
        transport: SocketDatagramTransport,
        mock_udp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        transport.close()

        # Assert
        assert mock_udp_socket.mock_calls == [mocker.call.close()]

    @pytest.mark.parametrize("max_datagram_size", [None, 1024], ids=lambda p: f"max_datagram_size=={p}", indirect=True)
    def test____recv_noblock____default(
        self,
        max_datagram_size: int | None,
        transport: SocketDatagramTransport,
        mock_udp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_udp_socket.recv.return_value = mocker.sentinel.bytes

        # Act
        result = transport.recv_noblock()

        # Assert
        if max_datagram_size is None:
            mock_udp_socket.recv.assert_called_once_with(MAX_DATAGRAM_BUFSIZE)
        else:
            mock_udp_socket.recv.assert_called_once_with(max_datagram_size)
        mock_udp_socket.fileno.assert_not_called()
        assert result is mocker.sentinel.bytes

    @pytest.mark.parametrize("error", [BlockingIOError, InterruptedError])
    @pytest.mark.parametrize("max_datagram_size", [None, 1024], ids=lambda p: f"max_datagram_size=={p}", indirect=True)
    def test____recv_noblock____blocking_error(
        self,
        max_datagram_size: int | None,
        error: type[OSError],
        transport: SocketDatagramTransport,
        mock_udp_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_udp_socket.recv.side_effect = error

        # Act
        with pytest.raises(WouldBlockOnRead) as exc_info:
            transport.recv_noblock()

        # Assert
        if max_datagram_size is None:
            mock_udp_socket.recv.assert_called_once_with(MAX_DATAGRAM_BUFSIZE)
        else:
            mock_udp_socket.recv.assert_called_once_with(max_datagram_size)
        mock_udp_socket.fileno.assert_called_once()
        assert exc_info.value.fileno is mock_udp_socket.fileno.return_value

    def test____send_noblock____default(
        self,
        transport: SocketDatagramTransport,
        mock_udp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_udp_socket.send.return_value = mocker.sentinel.nb_bytes_sent

        # Act
        result = transport.send_noblock(mocker.sentinel.data)

        # Assert
        mock_udp_socket.send.assert_called_once_with(mocker.sentinel.data)
        mock_udp_socket.fileno.assert_not_called()
        assert result is None

    @pytest.mark.parametrize("error", [BlockingIOError, InterruptedError])
    def test____send_noblock____blocking_error(
        self,
        error: type[OSError],
        transport: SocketDatagramTransport,
        mock_udp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_udp_socket.send.side_effect = error

        # Act
        with pytest.raises(WouldBlockOnWrite) as exc_info:
            transport.send_noblock(mocker.sentinel.data)

        # Assert
        mock_udp_socket.send.assert_called_once_with(mocker.sentinel.data)
        mock_udp_socket.fileno.assert_called_once()
        assert exc_info.value.fileno is mock_udp_socket.fileno.return_value
