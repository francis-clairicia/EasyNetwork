# mypy: disable-error-code=func-returns-value

from __future__ import annotations

import errno
import math
import os
from socket import SHUT_RDWR, SHUT_WR
from typing import TYPE_CHECKING

from easynetwork.api_sync.lowlevel.transports.base_selector import WouldBlockOnRead, WouldBlockOnWrite
from easynetwork.api_sync.lowlevel.transports.socket import SocketDatagramTransport, SocketStreamTransport
from easynetwork.tools.constants import MAX_DATAGRAM_BUFSIZE
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
        assert isinstance(transport.get_extra_info("socket"), SocketProxy)
        assert transport.get_extra_info("sockname") == ("local_address", 11111)
        assert transport.get_extra_info("peername") == ("remote_address", 12345)
        mock_tcp_socket.getsockname.assert_called_once_with()
        mock_tcp_socket.getpeername.assert_called_once_with()
        mock_tcp_socket.setblocking.assert_called_once_with(False)
        mock_tcp_socket.settimeout.assert_not_called()

    def test____dunder_init____getsockname_raises_OSError(
        self,
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_tcp_socket.getsockname.side_effect = OSError(errno.EINVAL, os.strerror(errno.EINVAL))

        # Act
        transport = SocketStreamTransport(mock_tcp_socket, math.inf)

        # Assert
        assert isinstance(transport.get_extra_info("socket"), SocketProxy)
        assert transport.get_extra_info("sockname") is None
        assert transport.get_extra_info("peername") == ("remote_address", 12345)
        mock_tcp_socket.getsockname.assert_called_once_with()
        mock_tcp_socket.getpeername.assert_called_once_with()
        mock_tcp_socket.setblocking.assert_called_once_with(False)
        mock_tcp_socket.settimeout.assert_not_called()

    def test____dunder_init____getpeername_raises_OSError(
        self,
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_tcp_socket.getpeername.side_effect = OSError(errno.ENOTCONN, os.strerror(errno.ENOTCONN))

        # Act
        transport = SocketStreamTransport(mock_tcp_socket, math.inf)

        # Assert
        assert isinstance(transport.get_extra_info("socket"), SocketProxy)
        assert transport.get_extra_info("sockname") == ("local_address", 11111)
        assert transport.get_extra_info("peername") is None
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
        assert isinstance(transport.get_extra_info("socket"), SocketProxy)
        assert transport.get_extra_info("sockname") == ("local_address", 11111)
        assert transport.get_extra_info("peername") == ("remote_address", 12345)
        mock_udp_socket.getsockname.assert_called_once_with()
        mock_udp_socket.getpeername.assert_called_once_with()
        mock_udp_socket.setblocking.assert_called_once_with(False)
        mock_udp_socket.settimeout.assert_not_called()

    def test____dunder_init____getsockname_raises_OSError(
        self,
        mock_udp_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_udp_socket.getsockname.side_effect = OSError(errno.EINVAL, os.strerror(errno.EINVAL))

        # Act
        transport = SocketDatagramTransport(mock_udp_socket, math.inf)

        # Assert
        assert isinstance(transport.get_extra_info("socket"), SocketProxy)
        assert transport.get_extra_info("sockname") is None
        assert transport.get_extra_info("peername") == ("remote_address", 12345)
        mock_udp_socket.getsockname.assert_called_once_with()
        mock_udp_socket.getpeername.assert_called_once_with()
        mock_udp_socket.setblocking.assert_called_once_with(False)
        mock_udp_socket.settimeout.assert_not_called()

    def test____dunder_init____getpeername_raises_OSError(
        self,
        mock_udp_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_udp_socket.getpeername.side_effect = OSError(errno.ENOTCONN, os.strerror(errno.ENOTCONN))

        # Act
        transport = SocketDatagramTransport(mock_udp_socket, math.inf)

        # Assert
        assert isinstance(transport.get_extra_info("socket"), SocketProxy)
        assert transport.get_extra_info("sockname") == ("local_address", 11111)
        assert transport.get_extra_info("peername") is None
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
