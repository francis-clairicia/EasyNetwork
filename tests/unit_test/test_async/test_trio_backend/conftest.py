from __future__ import annotations

from collections.abc import Callable
from socket import AF_INET, IPPROTO_TCP, IPPROTO_UDP, SOCK_DGRAM, SOCK_STREAM
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.fixture
def mock_trio_socket_from_stdlib(mocker: MockerFixture) -> MagicMock:
    return mocker.patch("trio.socket.from_stdlib_socket", autospec=True)


@pytest.fixture
def mock_trio_socket_factory(mocker: MockerFixture) -> Callable[[], MagicMock]:
    import trio

    def factory(family: int = -1, type: int = -1, proto: int = -1, fileno: int = 123) -> MagicMock:
        if family == -1:
            family = AF_INET
        if type == -1:
            type = SOCK_STREAM
        if proto == -1:
            proto = 0
        mock_socket = mocker.NonCallableMagicMock(spec=trio.socket.SocketType)
        mock_socket.family = family
        mock_socket.type = type
        mock_socket.proto = proto
        mock_socket.fileno.return_value = fileno

        def close_side_effect() -> None:
            mock_socket.fileno.return_value = -1

        def detached_side_effect() -> int:
            to_return, mock_socket.fileno.return_value = mock_socket.fileno.return_value, -1
            return to_return

        mock_socket.close.side_effect = close_side_effect
        mock_socket.detach.side_effect = detached_side_effect
        return mock_socket

    return factory


@pytest.fixture
def mock_trio_tcp_socket_factory(mock_trio_socket_factory: Callable[[int, int, int], MagicMock]) -> Callable[[], MagicMock]:
    def factory(family: int = -1) -> MagicMock:
        return mock_trio_socket_factory(family, SOCK_STREAM, IPPROTO_TCP)

    return factory


@pytest.fixture
def mock_trio_tcp_socket(mock_trio_tcp_socket_factory: Callable[[], MagicMock]) -> MagicMock:
    return mock_trio_tcp_socket_factory()


@pytest.fixture
def mock_trio_udp_socket_factory(mock_trio_socket_factory: Callable[[int, int, int], MagicMock]) -> Callable[[], MagicMock]:
    def factory(family: int = -1) -> MagicMock:
        return mock_trio_socket_factory(family, SOCK_DGRAM, IPPROTO_UDP)

    return factory


@pytest.fixture
def mock_trio_udp_socket(mock_trio_udp_socket_factory: Callable[[], MagicMock]) -> MagicMock:
    return mock_trio_udp_socket_factory()


@pytest.fixture
def mock_trio_socket_stream_factory(
    mocker: MockerFixture,
    mock_trio_tcp_socket_factory: Callable[[], MagicMock],
) -> Callable[[], MagicMock]:
    import trio

    def factory(socket: trio.socket.SocketType | None = None) -> MagicMock:
        mock_stream = mocker.NonCallableMagicMock(spec=trio.SocketStream)
        if socket is None:
            mock_stream.socket = mock_trio_tcp_socket_factory()
        else:
            mock_stream.socket = socket

        async def aclose_side_effect() -> None:
            mock_stream.socket.close()

        mock_stream.aclose.side_effect = aclose_side_effect
        return mock_stream

    return factory


@pytest.fixture
def mock_trio_socket_stream(mock_trio_socket_stream_factory: Callable[[], MagicMock]) -> MagicMock:
    return mock_trio_socket_stream_factory()


@pytest.fixture
def mock_trio_socket_listener_factory(
    mocker: MockerFixture,
    mock_trio_tcp_socket_factory: Callable[[], MagicMock],
) -> Callable[[], MagicMock]:
    import trio

    def factory(socket: trio.socket.SocketType | None = None) -> MagicMock:
        mock_stream = mocker.NonCallableMagicMock(spec=trio.SocketListener)
        if socket is None:
            mock_stream.socket = mock_trio_tcp_socket_factory()
        else:
            mock_stream.socket = socket

        async def aclose_side_effect() -> None:
            mock_stream.socket.close()

        mock_stream.aclose.side_effect = aclose_side_effect
        return mock_stream

    return factory


@pytest.fixture
def mock_trio_socket_listener(mock_trio_socket_listener_factory: Callable[[], MagicMock]) -> MagicMock:
    return mock_trio_socket_listener_factory()
