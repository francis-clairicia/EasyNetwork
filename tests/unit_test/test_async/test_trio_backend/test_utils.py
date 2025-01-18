from __future__ import annotations

import errno
import socket
from typing import TYPE_CHECKING, Any

from easynetwork.lowlevel._utils import error_from_errno

import pytest

if TYPE_CHECKING:
    from unittest.mock import AsyncMock, MagicMock

    from pytest_mock import MockerFixture


@pytest.mark.feature_trio
def test____convert_trio_resource_errors____ClosedResourceError() -> None:
    # Arrange
    import trio

    from easynetwork.lowlevel.api_async.backend._trio._trio_utils import convert_trio_resource_errors

    # Act
    with pytest.raises(OSError) as exc_info:
        with convert_trio_resource_errors(broken_resource_errno=errno.ECONNABORTED):
            try:
                raise error_from_errno(errno.EBADF)
            except OSError:
                raise trio.ClosedResourceError from None

    # Assert
    assert exc_info.value.errno == errno.EBADF
    assert isinstance(exc_info.value.__cause__, trio.ClosedResourceError)
    assert exc_info.value.__suppress_context__


@pytest.mark.feature_trio
def test____convert_trio_resource_errors____BusyResourceError() -> None:
    # Arrange
    import trio

    from easynetwork.lowlevel.api_async.backend._trio._trio_utils import convert_trio_resource_errors

    # Act
    with pytest.raises(OSError) as exc_info:
        with convert_trio_resource_errors(broken_resource_errno=errno.ECONNABORTED):
            raise trio.BusyResourceError

    # Assert
    assert exc_info.value.errno == errno.EBUSY
    assert isinstance(exc_info.value.__cause__, trio.BusyResourceError)
    assert exc_info.value.__suppress_context__


@pytest.mark.feature_trio
@pytest.mark.parametrize("broken_resource_errno", [errno.ECONNABORTED, errno.EPIPE])
def test____convert_trio_resource_errors____BrokenResourceError____arbitrary(broken_resource_errno: int) -> None:
    # Arrange
    import trio

    from easynetwork.lowlevel.api_async.backend._trio._trio_utils import convert_trio_resource_errors

    # Act
    with pytest.raises(OSError) as exc_info:
        with convert_trio_resource_errors(broken_resource_errno=broken_resource_errno):
            raise trio.BrokenResourceError

    # Assert
    assert exc_info.value.errno == broken_resource_errno
    assert isinstance(exc_info.value.__cause__, trio.BrokenResourceError)
    assert exc_info.value.__suppress_context__


@pytest.mark.feature_trio
@pytest.mark.parametrize("broken_resource_errno", [errno.ECONNABORTED, errno.ECONNRESET, errno.EPIPE, errno.ENOTCONN])
def test____convert_trio_resource_errors____BrokenResourceError____because_of_OSError(broken_resource_errno: int) -> None:
    # Arrange
    import trio

    from easynetwork.lowlevel.api_async.backend._trio._trio_utils import convert_trio_resource_errors

    initial_error = error_from_errno(broken_resource_errno)

    # Act
    with pytest.raises(OSError) as exc_info:
        with convert_trio_resource_errors(broken_resource_errno=errno.ECONNABORTED):
            try:
                raise initial_error
            except OSError as exc:
                raise trio.BrokenResourceError from exc

    # Assert
    assert exc_info.value is initial_error
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__


@pytest.mark.feature_trio
def test____convert_trio_resource_errors____other_exceptions() -> None:
    # Arrange
    from easynetwork.lowlevel.api_async.backend._trio._trio_utils import convert_trio_resource_errors

    initial_error = ValueError("invalid bufsize")

    # Act
    with pytest.raises(ValueError) as exc_info:
        with convert_trio_resource_errors(broken_resource_errno=errno.ECONNABORTED):
            raise initial_error

    # Assert
    assert exc_info.value is initial_error


@pytest.mark.feature_trio(async_test_auto_mark=True)
class TestSocketConnect:
    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_trio_lowlevel_wait_writable(mocker: MockerFixture) -> AsyncMock:
        import trio

        async def wait_writable(sock: Any) -> None:
            await trio.lowlevel.checkpoint()

        return mocker.patch("trio.lowlevel.wait_writable", autospec=True, side_effect=wait_writable)

    async def test____connect_socket____non_blocking(
        self,
        mock_tcp_socket: MagicMock,
        mock_trio_lowlevel_wait_writable: AsyncMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from easynetwork.lowlevel.api_async.backend._trio._trio_utils import connect_sock_to_resolved_address

        mock_tcp_socket.getsockopt.return_value = 0
        mock_tcp_socket.connect.return_value = None

        # Act
        await connect_sock_to_resolved_address(mock_tcp_socket, ("127.0.0.1", 12345))

        # Assert
        assert mock_tcp_socket.mock_calls == [mocker.call.connect(("127.0.0.1", 12345))]
        mock_trio_lowlevel_wait_writable.assert_not_awaited()

    async def test____connect_socket____blocking(
        self,
        mock_tcp_socket: MagicMock,
        mock_trio_lowlevel_wait_writable: AsyncMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from easynetwork.lowlevel.api_async.backend._trio._trio_utils import connect_sock_to_resolved_address

        mock_tcp_socket.getsockopt.side_effect = [0]
        mock_tcp_socket.connect.side_effect = [BlockingIOError]

        # Act
        await connect_sock_to_resolved_address(mock_tcp_socket, ("127.0.0.1", 12345))

        # Assert
        assert mock_tcp_socket.mock_calls == [
            mocker.call.connect(("127.0.0.1", 12345)),
            mocker.call.fileno(),
            mocker.call.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR),
        ]
        mock_trio_lowlevel_wait_writable.assert_awaited_once_with(mock_tcp_socket)

    async def test____connect_socket____blocking____connection_error(
        self,
        mock_tcp_socket: MagicMock,
        mock_trio_lowlevel_wait_writable: AsyncMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from easynetwork.lowlevel.api_async.backend._trio._trio_utils import connect_sock_to_resolved_address

        mock_tcp_socket.getsockopt.side_effect = [errno.ECONNREFUSED, 0]
        mock_tcp_socket.connect.side_effect = [BlockingIOError]

        # Act
        with pytest.raises(ConnectionRefusedError, match=r"^\[Errno \d+\] Could not connect to .+: .*$"):
            await connect_sock_to_resolved_address(mock_tcp_socket, ("127.0.0.1", 12345))

        # Assert
        assert mock_tcp_socket.mock_calls == [
            mocker.call.connect(("127.0.0.1", 12345)),
            mocker.call.fileno(),
            mocker.call.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR),
        ]
        mock_trio_lowlevel_wait_writable.assert_awaited_once_with(mock_tcp_socket)
