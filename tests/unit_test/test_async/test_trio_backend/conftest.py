from __future__ import annotations

from collections.abc import Callable
from socket import AF_INET, AF_INET6, IPPROTO_TCP, IPPROTO_UDP, SOCK_DGRAM, SOCK_STREAM
from typing import TYPE_CHECKING

from easynetwork.lowlevel.api_async.backend._trio.backend import TrioBackend

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.fixture(scope="package")
def trio_backend() -> TrioBackend:
    return TrioBackend()


@pytest.fixture
def mock_trio_socket_from_stdlib(mocker: MockerFixture) -> MagicMock:
    return mocker.patch("trio.socket.from_stdlib_socket", autospec=True)


@pytest.fixture
def mock_trio_socket_factory(mocker: MockerFixture) -> Callable[[], MagicMock]:
    from types import MethodType

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
        mock_socket.connect.return_value = None
        mock_socket.bind.return_value = None
        for async_method in ("recv", "recv_into", "recvfrom", "recvfrom_into", "send", "sendto", "sendmsg"):
            if hasattr(mock_socket, async_method):
                setattr(
                    mock_socket,
                    async_method,
                    mocker.AsyncMock(spec=MethodType(getattr(trio.socket.SocketType, async_method), mock_socket)),
                )
        return mock_socket

    return factory


@pytest.fixture
def mock_trio_tcp_socket_factory(mock_trio_socket_factory: Callable[[int, int, int, int], MagicMock]) -> Callable[[], MagicMock]:
    def factory(family: int = -1, fileno: int = 123) -> MagicMock:
        assert family in {AF_INET, AF_INET6, -1}
        return mock_trio_socket_factory(family, SOCK_STREAM, IPPROTO_TCP, fileno)

    return factory


@pytest.fixture
def mock_trio_tcp_socket(mock_trio_tcp_socket_factory: Callable[[], MagicMock]) -> MagicMock:
    return mock_trio_tcp_socket_factory()


@pytest.fixture
def mock_trio_udp_socket_factory(mock_trio_socket_factory: Callable[[int, int, int, int], MagicMock]) -> Callable[[], MagicMock]:
    def factory(family: int = -1, fileno: int = 123) -> MagicMock:
        assert family in {AF_INET, AF_INET6, -1}
        return mock_trio_socket_factory(family, SOCK_DGRAM, IPPROTO_UDP, fileno)

    return factory


@pytest.fixture
def mock_trio_udp_socket(mock_trio_udp_socket_factory: Callable[[], MagicMock]) -> MagicMock:
    return mock_trio_udp_socket_factory()


@pytest.fixture
def mock_trio_unix_stream_socket_factory(
    mock_trio_socket_factory: Callable[[int, int, int, int], MagicMock],
) -> Callable[[], MagicMock]:
    from ....fixtures.socket import AF_UNIX_or_skip

    def factory(fileno: int = 123) -> MagicMock:
        return mock_trio_socket_factory(AF_UNIX_or_skip(), SOCK_STREAM, 0, fileno)

    return factory


@pytest.fixture
def mock_trio_unix_stream_socket(mock_trio_unix_stream_socket_factory: Callable[[], MagicMock]) -> MagicMock:
    return mock_trio_unix_stream_socket_factory()


@pytest.fixture
def mock_trio_unix_datagram_socket_factory(
    mock_trio_socket_factory: Callable[[int, int, int, int], MagicMock],
) -> Callable[[], MagicMock]:
    from ....fixtures.socket import AF_UNIX_or_skip

    def factory(fileno: int = 123) -> MagicMock:
        return mock_trio_socket_factory(AF_UNIX_or_skip(), SOCK_DGRAM, 0, fileno)

    return factory


@pytest.fixture
def mock_trio_unix_datagram_socket(mock_trio_unix_datagram_socket_factory: Callable[[], MagicMock]) -> MagicMock:
    return mock_trio_unix_datagram_socket_factory()


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
