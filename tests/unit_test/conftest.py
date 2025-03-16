from __future__ import annotations

import itertools
import os
from collections.abc import Callable
from socket import AF_INET, AF_INET6, IPPROTO_TCP, IPPROTO_UDP, SOCK_DGRAM, SOCK_STREAM, socket as Socket
from ssl import SSLContext, SSLObject, SSLSocket
from typing import TYPE_CHECKING, Any

from easynetwork.converter import AbstractPacketConverterComposite
from easynetwork.lowlevel.socket import UnixCredentials
from easynetwork.protocol import BufferedStreamProtocol, DatagramProtocol, StreamProtocol
from easynetwork.serializers.abc import (
    AbstractIncrementalPacketSerializer,
    AbstractPacketSerializer,
    BufferedIncrementalPacketSerializer,
)

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.fixture
def SO_REUSEPORT(monkeypatch: pytest.MonkeyPatch) -> int:
    import socket

    if not hasattr(socket, "SO_REUSEPORT"):
        monkeypatch.setattr("socket.SO_REUSEPORT", 15, raising=False)
    return getattr(socket, "SO_REUSEPORT")


@pytest.fixture
def remove_SO_REUSEPORT_support(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr("socket.SO_REUSEPORT", raising=False)


@pytest.fixture
def fake_ucred() -> UnixCredentials:
    return UnixCredentials(pid=os.getpid(), uid=1000, gid=1000)


@pytest.fixture
def mock_get_peer_credentials(mocker: MockerFixture) -> MagicMock:
    mock_get_peer_credentials = mocker.MagicMock(
        name="mock_get_peer_credentials",
        spec=lambda sock: None,
    )

    def patch_get_peer_credentials_impl() -> Callable[[Any], UnixCredentials]:
        return mock_get_peer_credentials

    mocker.patch("easynetwork.lowlevel._unix_utils._get_peer_credentials_impl_from_platform", patch_get_peer_credentials_impl)
    return mock_get_peer_credentials


@pytest.fixture
def mock_socket_factory(mocker: MockerFixture) -> Callable[[], MagicMock]:
    fileno_counter = itertools.count()

    def factory(family: int = -1, type: int = -1, proto: int = -1, fileno: int | None = None) -> MagicMock:
        if family == -1:
            family = AF_INET
        if type == -1:
            type = SOCK_STREAM
        if proto == -1:
            proto = 0
        if fileno is None:
            fileno = 123 + next(fileno_counter)
        mock_socket = mocker.NonCallableMagicMock(spec=Socket)
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
        return mock_socket

    return factory


@pytest.fixture(scope="package", autouse=True)
def original_socket_cls() -> type[Socket]:
    return Socket


@pytest.fixture
def mock_tcp_socket_factory(mock_socket_factory: Callable[[int, int, int, int | None], MagicMock]) -> Callable[[], MagicMock]:
    def factory(family: int = -1, fileno: int | None = None) -> MagicMock:
        assert family in {AF_INET, AF_INET6, -1}
        return mock_socket_factory(family, SOCK_STREAM, IPPROTO_TCP, fileno)

    return factory


@pytest.fixture
def mock_tcp_socket(mock_tcp_socket_factory: Callable[[], MagicMock]) -> MagicMock:
    return mock_tcp_socket_factory()


@pytest.fixture
def mock_udp_socket_factory(mock_socket_factory: Callable[[int, int, int, int | None], MagicMock]) -> Callable[[], MagicMock]:
    def factory(family: int = -1, fileno: int | None = None) -> MagicMock:
        assert family in {AF_INET, AF_INET6, -1}
        return mock_socket_factory(family, SOCK_DGRAM, IPPROTO_UDP, fileno)

    return factory


@pytest.fixture
def mock_udp_socket(mock_udp_socket_factory: Callable[[], MagicMock]) -> MagicMock:
    return mock_udp_socket_factory()


@pytest.fixture
def mock_unix_stream_socket_factory(
    mock_socket_factory: Callable[[int, int, int, int | None], MagicMock],
) -> Callable[[], MagicMock]:
    from ..fixtures.socket import AF_UNIX_or_skip

    def factory(fileno: int | None = None) -> MagicMock:
        return mock_socket_factory(AF_UNIX_or_skip(), SOCK_STREAM, 0, fileno)

    return factory


@pytest.fixture
def mock_unix_stream_socket(mock_unix_stream_socket_factory: Callable[[], MagicMock]) -> MagicMock:
    return mock_unix_stream_socket_factory()


@pytest.fixture
def mock_unix_datagram_socket_factory(
    mock_socket_factory: Callable[[int, int, int, int | None], MagicMock],
) -> Callable[[], MagicMock]:
    from ..fixtures.socket import AF_UNIX_or_skip

    def factory(fileno: int | None = None) -> MagicMock:
        return mock_socket_factory(AF_UNIX_or_skip(), SOCK_DGRAM, 0, fileno)

    return factory


@pytest.fixture
def mock_unix_datagram_socket(mock_unix_datagram_socket_factory: Callable[[], MagicMock]) -> MagicMock:
    return mock_unix_datagram_socket_factory()


@pytest.fixture
def mock_ssl_socket_factory(mocker: MockerFixture) -> Callable[[], MagicMock]:
    fileno_counter = itertools.count()

    def factory(family: int = -1) -> MagicMock:
        if family == -1:
            family = AF_INET
        mock_socket = mocker.NonCallableMagicMock(spec=SSLSocket)
        mock_socket.family = family
        mock_socket.type = SOCK_STREAM
        mock_socket.proto = IPPROTO_TCP
        mock_socket.fileno.return_value = 123 + next(fileno_counter)
        mock_socket.do_handshake.return_value = None
        mock_socket.unwrap.return_value = None

        def close_side_effect() -> None:
            mock_socket.fileno.return_value = -1

        def detached_side_effect() -> int:
            to_return, mock_socket.fileno.return_value = mock_socket.fileno.return_value, -1
            return to_return

        mock_socket.close.side_effect = close_side_effect
        mock_socket.detach.side_effect = detached_side_effect
        mock_socket.connect.return_value = None
        mock_socket.bind.return_value = None
        return mock_socket

    return factory


@pytest.fixture
def mock_ssl_socket(mock_ssl_socket_factory: Callable[[], MagicMock]) -> MagicMock:
    return mock_ssl_socket_factory()


@pytest.fixture
def mock_ssl_context_factory(mocker: MockerFixture) -> Callable[[], MagicMock]:
    def factory() -> MagicMock:
        mock_context = mocker.NonCallableMagicMock(spec=SSLContext)
        mock_context.check_hostname = True
        mock_context.options = 0
        return mock_context

    return factory


@pytest.fixture
def mock_ssl_context(mock_ssl_context_factory: Callable[[], MagicMock]) -> MagicMock:
    return mock_ssl_context_factory()


@pytest.fixture
def mock_ssl_object_factory(mocker: MockerFixture) -> Callable[[], MagicMock]:
    def factory() -> MagicMock:
        mock_ssl_object = mocker.NonCallableMagicMock(spec=SSLObject)
        mock_ssl_object.do_handshake.return_value = None
        mock_ssl_object.unwrap.return_value = None
        return mock_ssl_object

    return factory


@pytest.fixture
def mock_ssl_object(mock_ssl_object_factory: Callable[[], MagicMock]) -> MagicMock:
    return mock_ssl_object_factory()


@pytest.fixture
def mock_serializer_factory(mocker: MockerFixture) -> Callable[[], Any]:
    return lambda: mocker.NonCallableMagicMock(spec=AbstractPacketSerializer)


@pytest.fixture
def mock_serializer(mock_serializer_factory: Callable[[], Any]) -> Any:
    return mock_serializer_factory()


@pytest.fixture
def mock_incremental_serializer_factory(mocker: MockerFixture) -> Callable[[], Any]:
    return lambda: mocker.NonCallableMagicMock(spec=AbstractIncrementalPacketSerializer)


@pytest.fixture
def mock_incremental_serializer(mock_incremental_serializer_factory: Callable[[], Any]) -> Any:
    return mock_incremental_serializer_factory()


@pytest.fixture
def mock_buffered_incremental_serializer_factory(mocker: MockerFixture) -> Callable[[], Any]:
    return lambda: mocker.NonCallableMagicMock(
        spec=BufferedIncrementalPacketSerializer,
        **{
            "create_deserializer_buffer.side_effect": lambda sizehint: memoryview(bytearray(sizehint)),
        },
    )


@pytest.fixture
def mock_buffered_incremental_serializer(mock_buffered_incremental_serializer_factory: Callable[[], Any]) -> Any:
    return mock_buffered_incremental_serializer_factory()


@pytest.fixture
def mock_converter_factory(mocker: MockerFixture) -> Callable[[], Any]:
    return lambda: mocker.NonCallableMagicMock(spec=AbstractPacketConverterComposite)


@pytest.fixture
def mock_converter(mock_converter_factory: Callable[[], Any]) -> Any:
    return mock_converter_factory()


@pytest.fixture
def mock_datagram_protocol_factory(mocker: MockerFixture) -> Callable[[], Any]:
    return lambda: mocker.NonCallableMagicMock(spec=DatagramProtocol)


@pytest.fixture
def mock_datagram_protocol(mock_datagram_protocol_factory: Callable[[], Any]) -> Any:
    return mock_datagram_protocol_factory()


@pytest.fixture
def mock_stream_protocol_factory(mocker: MockerFixture) -> Callable[[], Any]:
    return lambda: mocker.NonCallableMagicMock(spec=StreamProtocol)


@pytest.fixture
def mock_stream_protocol(mock_stream_protocol_factory: Callable[[], Any]) -> Any:
    return mock_stream_protocol_factory()


@pytest.fixture
def mock_buffered_stream_protocol_factory(
    mocker: MockerFixture,
) -> Callable[[], Any]:
    return lambda: mocker.NonCallableMagicMock(
        spec=BufferedStreamProtocol,
        **{
            "create_buffer.side_effect": lambda sizehint: memoryview(bytearray(sizehint)),
        },
    )


@pytest.fixture
def mock_buffered_stream_protocol(mock_buffered_stream_protocol_factory: Callable[[], Any]) -> Any:
    return mock_buffered_stream_protocol_factory()
