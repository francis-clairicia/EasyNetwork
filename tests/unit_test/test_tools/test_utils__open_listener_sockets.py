from __future__ import annotations

import errno
from collections.abc import Callable, Sequence
from socket import AF_INET, AF_INET6, IPPROTO_IPV6, IPPROTO_TCP, IPV6_V6ONLY, SO_REUSEADDR, SOCK_STREAM, SOL_SOCKET
from typing import TYPE_CHECKING, Any, cast

from easynetwork.lowlevel._utils import error_from_errno, open_listener_sockets_from_getaddrinfo_result

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.fixture
def mock_socket_ipv4(mock_socket_factory: Callable[[], MagicMock]) -> MagicMock:
    return mock_socket_factory()


@pytest.fixture
def mock_socket_ipv6(mock_socket_factory: Callable[[], MagicMock]) -> MagicMock:
    return mock_socket_factory()


@pytest.fixture(autouse=True)
def mock_socket_cls(mock_socket_ipv4: MagicMock, mock_socket_ipv6: MagicMock, mocker: MockerFixture) -> MagicMock:
    def side_effect(family: int, type: int, proto: int) -> MagicMock:
        if family == AF_INET6:
            used_socket = mock_socket_ipv6
        elif family == AF_INET:
            used_socket = mock_socket_ipv4
        else:
            raise error_from_errno(errno.EAFNOSUPPORT)

        used_socket.family = family
        used_socket.type = type
        used_socket.proto = proto
        return used_socket

    return mocker.patch("socket.socket", side_effect=side_effect)


@pytest.fixture
def addrinfo_list() -> Sequence[tuple[int, int, int, str, tuple[Any, ...]]]:
    return (
        (AF_INET, SOCK_STREAM, IPPROTO_TCP, "", ("0.0.0.0", 65432)),
        (AF_INET6, SOCK_STREAM, IPPROTO_TCP, "", ("::", 65432, 0, 0)),
    )


@pytest.mark.parametrize("reuse_address", [False, True], ids=lambda boolean: f"reuse_address=={boolean}")
@pytest.mark.parametrize("SO_REUSEADDR_available", [False, True], ids=lambda boolean: f"SO_REUSEADDR_available=={boolean}")
@pytest.mark.parametrize("SO_REUSEADDR_raise_error", [False, True], ids=lambda boolean: f"SO_REUSEADDR_raise_error=={boolean}")
@pytest.mark.parametrize("IPPROTO_IPV6_available", [False, True], ids=lambda boolean: f"IPPROTO_IPV6_available=={boolean}")
@pytest.mark.parametrize("reuse_port", [False, True], ids=lambda boolean: f"reuse_port=={boolean}")
def test____open_listener_sockets_from_getaddrinfo_result____create_listener_sockets(
    reuse_address: bool,
    SO_REUSEADDR_available: bool,
    SO_REUSEADDR_raise_error: bool,
    IPPROTO_IPV6_available: bool,
    reuse_port: bool,
    mock_socket_cls: MagicMock,
    mock_socket_ipv4: MagicMock,
    mock_socket_ipv6: MagicMock,
    addrinfo_list: Sequence[tuple[int, int, int, str, tuple[Any, ...]]],
    monkeypatch: pytest.MonkeyPatch,
    SO_REUSEPORT: int,
    mocker: MockerFixture,
) -> None:
    # Arrange
    if not SO_REUSEADDR_available:
        monkeypatch.delattr("socket.SO_REUSEADDR", raising=True)
    if not IPPROTO_IPV6_available:
        monkeypatch.delattr("socket.IPPROTO_IPV6", raising=False)
    if SO_REUSEADDR_raise_error:

        def setsockopt(level: int, opt: int, value: int, /) -> None:
            if level == SOL_SOCKET and opt == SO_REUSEADDR:
                raise OSError

        mock_socket_ipv4.setsockopt.side_effect = setsockopt
        mock_socket_ipv6.setsockopt.side_effect = setsockopt

    # Act
    sockets = cast(
        "list[MagicMock]",
        open_listener_sockets_from_getaddrinfo_result(
            addrinfo_list,
            reuse_address=reuse_address,
            reuse_port=reuse_port,
        ),
    )

    # Assert
    assert len(sockets) == len(addrinfo_list)
    assert mock_socket_cls.call_args_list == [mocker.call(f, t, p) for f, t, p, _, _ in addrinfo_list]
    for socket, (sock_family, _, _, _, sock_addr) in zip(sockets, addrinfo_list, strict=True):
        expected_setsockopt_calls: list[Any] = []
        if reuse_address and SO_REUSEADDR_available:
            expected_setsockopt_calls.append(mocker.call(SOL_SOCKET, SO_REUSEADDR, True))
        if reuse_port:
            expected_setsockopt_calls.append(mocker.call(SOL_SOCKET, SO_REUSEPORT, True))
        if sock_family == AF_INET6 and IPPROTO_IPV6_available:
            expected_setsockopt_calls.append(mocker.call(IPPROTO_IPV6, IPV6_V6ONLY, True))

        assert socket.setsockopt.mock_calls == expected_setsockopt_calls

        socket.bind.assert_called_once_with(sock_addr)
        socket.listen.assert_not_called()
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
    sockets = open_listener_sockets_from_getaddrinfo_result(addrinfo_list, reuse_address=True, reuse_port=False)

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
    with pytest.raises(ExceptionGroup, match=r"^Error when trying to create listeners \(1 sub-exception\)$") as exc_info:
        open_listener_sockets_from_getaddrinfo_result(addrinfo_list, reuse_address=True, reuse_port=False)

    # Assert
    os_errors, exc = exc_info.value.split(OSError)
    assert exc is None
    assert os_errors is not None
    assert len(os_errors.exceptions) == 1
    assert isinstance(os_errors.exceptions[0], OSError)
    assert os_errors.exceptions[0].errno == 1234

    s1.close.assert_called_once_with()
    s2.close.assert_called_once_with()


def test____open_listener_sockets_from_getaddrinfo_result____ipv6_scope_id_not_properly_extracted_from_address(
    mock_socket_cls: MagicMock,
    mock_socket_ipv6: MagicMock,
) -> None:
    # Arrange
    addrinfo_list: Sequence[tuple[int, int, int, str, tuple[Any, ...]]] = [
        (AF_INET6, SOCK_STREAM, IPPROTO_TCP, "", ("4e76:f928:6bbc:53ce:c01e:00d5:cdd5:6bbb%6", 65432, 0, 0)),
    ]
    mock_socket_cls.side_effect = [mock_socket_ipv6]

    # Act
    sockets = open_listener_sockets_from_getaddrinfo_result(addrinfo_list, reuse_address=True, reuse_port=False)

    # Assert
    assert sockets == [mock_socket_ipv6]
    mock_socket_ipv6.bind.assert_called_once_with(("4e76:f928:6bbc:53ce:c01e:00d5:cdd5:6bbb", 65432, 0, 6))
