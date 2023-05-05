# -*- coding: Utf-8 -*-

from __future__ import annotations

from socket import (
    AF_INET,
    AF_INET6,
    IPPROTO_IPV6,
    IPPROTO_TCP,
    IPV6_V6ONLY,
    SO_ERROR,
    SO_REUSEADDR,
    SOCK_STREAM,
    SOL_SOCKET,
    TCP_NODELAY,
)
from typing import TYPE_CHECKING, Any, Callable, Sequence, cast

from easynetwork.tools._utils import (
    check_real_socket_state,
    check_socket_family,
    concatenate_chunks,
    error_from_errno,
    open_listener_sockets_from_getaddrinfo_result,
    restore_timeout_at_end,
    set_reuseport,
    set_tcp_nodelay,
)

import pytest

from ..base import SUPPORTED_FAMILIES, UNSUPPORTED_FAMILIES

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.fixture
def mock_socket_cls(mock_tcp_socket_factory: Callable[[], MagicMock], mocker: MockerFixture) -> MagicMock:
    return mocker.patch("socket.socket", side_effect=lambda f, t, p: mock_tcp_socket_factory())


@pytest.fixture(params=list(SUPPORTED_FAMILIES))
def socket_family(request: Any) -> Any:
    import socket

    return getattr(socket, request.param)


@pytest.fixture
def addrinfo_list() -> Sequence[tuple[int, int, int, str, tuple[Any, ...]]]:
    return (
        (AF_INET, SOCK_STREAM, IPPROTO_TCP, "", ("0.0.0.0", 65432)),
        (AF_INET6, SOCK_STREAM, IPPROTO_TCP, "", ("::", 65432, 0, 0)),
    )


def test____error_from_errno____returns_OSError(mocker: MockerFixture) -> None:
    # Arrange
    errno: int = 123456
    mock_strerror = mocker.patch("os.strerror", return_value="errno message")

    # Act
    exception = error_from_errno(errno)

    # Assert
    assert isinstance(exception, OSError)
    assert exception.errno == errno
    assert exception.strerror == "errno message"
    mock_strerror.assert_called_once_with(errno)


def test____check_real_socket_state____socket_without_error(mock_tcp_socket: MagicMock, mocker: MockerFixture) -> None:
    # Arrange
    mock_tcp_socket.getsockopt.return_value = 0
    mock_error_from_errno = mocker.patch(f"{error_from_errno.__module__}.{error_from_errno.__qualname__}")

    # Act
    check_real_socket_state(mock_tcp_socket)

    # Assert
    mock_tcp_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_ERROR)
    mock_error_from_errno.assert_not_called()


def test____check_real_socket_state____socket_with_error(mock_tcp_socket: MagicMock, mocker: MockerFixture) -> None:
    # Arrange
    errno = 123456
    exception = OSError(errno, "errno message")
    mock_tcp_socket.getsockopt.return_value = errno
    mock_error_from_errno = mocker.patch(f"{error_from_errno.__module__}.{error_from_errno.__qualname__}", return_value=exception)

    # Act
    with pytest.raises(OSError) as exc_info:
        check_real_socket_state(mock_tcp_socket)

    # Assert
    assert exc_info.value is exception
    mock_tcp_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_ERROR)
    mock_error_from_errno.assert_called_once_with(errno)


def test____check_socket_family____valid_family(socket_family: int) -> None:
    # Arrange

    # Act
    check_socket_family(socket_family)

    # Assert
    ## There is no exception


@pytest.mark.parametrize("socket_family", list(UNSUPPORTED_FAMILIES), indirect=True)
def test____check_socket_family____invalid_family(socket_family: int) -> None:
    # Arrange

    # Act & Assert
    with pytest.raises(ValueError, match=r"^Only these families are supported: .+$"):
        check_socket_family(socket_family)

    # Assert


def test____restore_timeout_at_end____settimeout_to_default_at_scope_end(
    mock_tcp_socket: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange
    mock_tcp_socket.gettimeout.return_value = mocker.sentinel.default_timeout
    exception = Exception()

    # Act
    default_timeout: float | None = None
    with pytest.raises(Exception) as exc_info:
        with restore_timeout_at_end(mock_tcp_socket) as default_timeout:
            raise exception

    ## Ensure there is not a hidden exception
    assert exc_info.value is exception
    assert exception.__context__ is None and exception.__cause__ is None

    # Assert
    assert default_timeout is mocker.sentinel.default_timeout
    mock_tcp_socket.gettimeout.assert_called_once_with()
    mock_tcp_socket.settimeout.assert_called_once_with(mocker.sentinel.default_timeout)


def test____concanetate_chunks____join_several_bytestrings() -> None:
    # Arrange
    to_join = [b"a", b"b", b"cd", b"", b"efgh"]
    expected_result = b"abcdefgh"

    # Act
    result = concatenate_chunks(to_join)

    # Assert
    assert result == expected_result


def test____set_reuseport____setsockopt(
    mock_tcp_socket: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    SO_REUSEPORT: int = 123456
    mock_tcp_socket.setsockopt.return_value = None
    monkeypatch.setattr("socket.SO_REUSEPORT", SO_REUSEPORT, raising=False)

    # Act
    set_reuseport(mock_tcp_socket)

    # Assert
    mock_tcp_socket.setsockopt.assert_called_once_with(SOL_SOCKET, SO_REUSEPORT, True)


def test____set_reuseport____not_supported____not_defined(
    mock_tcp_socket: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    mock_tcp_socket.setsockopt.side_effect = OSError
    monkeypatch.delattr("socket.SO_REUSEPORT", raising=False)

    # Act
    with pytest.raises(ValueError, match=r"^reuse_port not supported by socket module$"):
        set_reuseport(mock_tcp_socket)

    # Assert
    mock_tcp_socket.setsockopt.assert_not_called()


def test____set_reuseport____not_supported____defined_but_not_implemented(
    mock_tcp_socket: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    SO_REUSEPORT: int = 123456
    mock_tcp_socket.setsockopt.side_effect = OSError
    monkeypatch.setattr("socket.SO_REUSEPORT", SO_REUSEPORT, raising=False)

    # Act
    with pytest.raises(
        ValueError, match=r"^reuse_port not supported by socket module, SO_REUSEPORT defined but not implemented\.$"
    ):
        set_reuseport(mock_tcp_socket)

    # Assert
    mock_tcp_socket.setsockopt.assert_called_once_with(SOL_SOCKET, SO_REUSEPORT, True)


def test____set_tcp_nodelay____setsockopt(
    mock_tcp_socket: MagicMock,
) -> None:
    # Arrange

    # Act
    set_tcp_nodelay(mock_tcp_socket)

    # Assert
    mock_tcp_socket.setsockopt.assert_called_once_with(IPPROTO_TCP, TCP_NODELAY, True)


@pytest.mark.parametrize("reuse_address", [False, True], ids=lambda boolean: f"reuse_address=={boolean}")
@pytest.mark.parametrize("reuse_port", [False, True], ids=lambda boolean: f"reuse_port=={boolean}")
def test____open_listener_sockets_from_getaddrinfo_result____create_listener_sockets(
    reuse_address: bool,
    reuse_port: bool,
    mock_socket_cls: MagicMock,
    mocker: MockerFixture,
    addrinfo_list: Sequence[tuple[int, int, int, str, tuple[Any, ...]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    SO_REUSEPORT: int = 123456
    monkeypatch.setattr("socket.SO_REUSEPORT", SO_REUSEPORT, raising=False)
    backlog: int = 123456

    # Act
    sockets = cast(
        "list[MagicMock]",
        open_listener_sockets_from_getaddrinfo_result(
            addrinfo_list,
            backlog=backlog,
            reuse_address=reuse_address,
            reuse_port=reuse_port,
        ),
    )

    # Assert
    assert len(sockets) == len(addrinfo_list)
    assert mock_socket_cls.mock_calls == [mocker.call(f, t, p) for f, t, p, _, _ in addrinfo_list]
    for socket, (sock_family, _, _, _, sock_addr) in zip(sockets, addrinfo_list, strict=True):
        if reuse_address:
            socket.setsockopt.assert_any_call(SOL_SOCKET, SO_REUSEADDR, True)
        if reuse_port:
            socket.setsockopt.assert_any_call(SOL_SOCKET, SO_REUSEPORT, True)
        if sock_family == AF_INET6:
            socket.setsockopt.assert_any_call(IPPROTO_IPV6, IPV6_V6ONLY, True)
        socket.bind.assert_called_once_with(sock_addr)
        socket.listen.assert_called_once_with(backlog)
        socket.close.assert_not_called()


def test____open_listener_sockets_from_getaddrinfo_result____ignore_bad_combinations(
    mock_socket_cls: MagicMock,
    mock_tcp_socket_factory: Callable[[], MagicMock],
    addrinfo_list: Sequence[tuple[int, int, int, str, tuple[Any, ...]]],
) -> None:
    # Arrange
    assert len(addrinfo_list) == 2  # In prevention
    mock_socket_cls.side_effect = [mock_tcp_socket_factory(), OSError]

    # Act
    sockets = open_listener_sockets_from_getaddrinfo_result(addrinfo_list, backlog=10, reuse_address=True, reuse_port=False)

    # Assert
    assert len(sockets) == 1


def test____open_listener_sockets_from_getaddrinfo_result____bind_failed(
    mock_socket_cls: MagicMock,
    mock_tcp_socket_factory: Callable[[], MagicMock],
    addrinfo_list: Sequence[tuple[int, int, int, str, tuple[Any, ...]]],
) -> None:
    # Arrange
    assert len(addrinfo_list) == 2  # In prevention
    s1, s2 = mock_tcp_socket_factory(), mock_tcp_socket_factory()
    mock_socket_cls.side_effect = [s1, s2]
    s2.bind.side_effect = OSError(1234, "error message")

    # Act
    with pytest.raises(ExceptionGroup) as exc_info:
        open_listener_sockets_from_getaddrinfo_result(addrinfo_list, backlog=10, reuse_address=True, reuse_port=False)

    # Assert
    os_errors, exc = exc_info.value.split(OSError)
    assert exc is None
    assert os_errors is not None
    assert len(os_errors.exceptions) == 1
    assert isinstance(os_errors.exceptions[0], OSError)
    assert os_errors.exceptions[0].errno == 1234

    s1.close.assert_called_once_with()
    s2.close.assert_called_once_with()
