from __future__ import annotations

import errno
import socket
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from unittest.mock import AsyncMock, MagicMock

    from easynetwork.lowlevel.api_async.backend._trio.dns_resolver import TrioDNSResolver

    from pytest_mock import MockerFixture


@pytest.mark.feature_trio(async_test_auto_mark=True)
class TestTrioDNSResolver:
    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_trio_lowlevel_wait_writable(mocker: MockerFixture) -> AsyncMock:
        import trio

        async def wait_writable(sock: Any) -> None:
            await trio.lowlevel.checkpoint()

        return mocker.patch("trio.lowlevel.wait_writable", autospec=True, side_effect=wait_writable)

    @pytest.fixture
    @staticmethod
    def dns_resolver() -> TrioDNSResolver:
        from easynetwork.lowlevel.api_async.backend._trio.dns_resolver import TrioDNSResolver

        return TrioDNSResolver()

    async def test____connect_socket____works____non_blocking(
        self,
        dns_resolver: TrioDNSResolver,
        mock_tcp_socket: MagicMock,
        mock_trio_lowlevel_wait_writable: AsyncMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_tcp_socket.getsockopt.return_value = 0
        mock_tcp_socket.connect.return_value = None

        # Act
        await dns_resolver.connect_socket(mock_tcp_socket, ("127.0.0.1", 12345))

        # Assert
        assert mock_tcp_socket.mock_calls == [mocker.call.connect(("127.0.0.1", 12345))]
        mock_trio_lowlevel_wait_writable.assert_not_awaited()

    async def test____connect_socket____works____blocking(
        self,
        dns_resolver: TrioDNSResolver,
        mock_tcp_socket: MagicMock,
        mock_trio_lowlevel_wait_writable: AsyncMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_tcp_socket.getsockopt.side_effect = [0]
        mock_tcp_socket.connect.side_effect = [BlockingIOError]

        # Act
        await dns_resolver.connect_socket(mock_tcp_socket, ("127.0.0.1", 12345))

        # Assert
        assert mock_tcp_socket.mock_calls == [
            mocker.call.connect(("127.0.0.1", 12345)),
            mocker.call.fileno(),
            mocker.call.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR),
        ]
        mock_trio_lowlevel_wait_writable.assert_awaited_once_with(mock_tcp_socket)

    async def test____connect_socket____works____blocking____connection_error(
        self,
        dns_resolver: TrioDNSResolver,
        mock_tcp_socket: MagicMock,
        mock_trio_lowlevel_wait_writable: AsyncMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_tcp_socket.getsockopt.side_effect = [errno.ECONNREFUSED, 0]
        mock_tcp_socket.connect.side_effect = [BlockingIOError]

        # Act
        with pytest.raises(ConnectionRefusedError, match=r"^\[Errno \d+\] Could not connect to .+: .*$"):
            await dns_resolver.connect_socket(mock_tcp_socket, ("127.0.0.1", 12345))

        # Assert
        assert mock_tcp_socket.mock_calls == [
            mocker.call.connect(("127.0.0.1", 12345)),
            mocker.call.fileno(),
            mocker.call.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR),
        ]
        mock_trio_lowlevel_wait_writable.assert_awaited_once_with(mock_tcp_socket)
