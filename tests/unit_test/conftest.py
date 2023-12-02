from __future__ import annotations

from collections.abc import Callable
from socket import AF_INET, IPPROTO_TCP, IPPROTO_UDP, SOCK_DGRAM, SOCK_STREAM, socket as Socket
from ssl import SSLContext, SSLSocket
from typing import TYPE_CHECKING, Any

from easynetwork.converter import AbstractPacketConverterComposite
from easynetwork.exceptions import UnsupportedOperation
from easynetwork.protocol import BufferedStreamReceiver, DatagramProtocol, StreamProtocol
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
def mock_socket_factory(mocker: MockerFixture) -> Callable[[], MagicMock]:
    def factory() -> MagicMock:
        mock_socket = mocker.NonCallableMagicMock(spec=Socket)
        mock_socket.family = AF_INET
        mock_socket.type = -1
        mock_socket.proto = 0
        mock_socket.fileno.return_value = 123

        def close_side_effect() -> None:
            mock_socket.fileno.return_value = -1

        def detached_side_effect() -> int:
            to_return, mock_socket.fileno.return_value = mock_socket.fileno.return_value, -1
            return to_return

        mock_socket.close.side_effect = close_side_effect
        mock_socket.detach.side_effect = detached_side_effect
        return mock_socket

    return factory


@pytest.fixture(scope="package", autouse=True)
def original_socket_cls() -> type[Socket]:
    return Socket


@pytest.fixture
def mock_tcp_socket_factory(mock_socket_factory: Callable[[], MagicMock]) -> Callable[[], MagicMock]:
    def factory() -> MagicMock:
        mock_socket = mock_socket_factory()
        mock_socket.type = SOCK_STREAM
        mock_socket.proto = IPPROTO_TCP
        return mock_socket

    return factory


@pytest.fixture
def mock_tcp_socket(mock_tcp_socket_factory: Callable[[], MagicMock]) -> MagicMock:
    return mock_tcp_socket_factory()


@pytest.fixture
def mock_udp_socket_factory(mock_socket_factory: Callable[[], MagicMock]) -> Callable[[], MagicMock]:
    def factory() -> MagicMock:
        mock_socket = mock_socket_factory()
        mock_socket.type = SOCK_DGRAM
        mock_socket.proto = IPPROTO_UDP
        return mock_socket

    return factory


@pytest.fixture
def mock_udp_socket(mock_udp_socket_factory: Callable[[], MagicMock]) -> MagicMock:
    return mock_udp_socket_factory()


@pytest.fixture
def mock_ssl_socket_factory(mocker: MockerFixture) -> Callable[[], MagicMock]:
    def factory() -> MagicMock:
        mock_socket = mocker.NonCallableMagicMock(spec=SSLSocket)
        mock_socket.family = AF_INET
        mock_socket.type = SOCK_STREAM
        mock_socket.proto = IPPROTO_TCP
        mock_socket.fileno.return_value = 123
        mock_socket.do_handshake.return_value = None
        mock_socket.unwrap.return_value = None

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
def mock_serializer_factory(mocker: MockerFixture) -> Callable[[], Any]:
    return lambda: mocker.NonCallableMagicMock(spec=AbstractPacketSerializer)


@pytest.fixture
def mock_serializer(mock_serializer_factory: Callable[[], Any]) -> Any:
    return mock_serializer_factory()


@pytest.fixture(params=[None, "buffered"], ids=lambda p: f"incremental_serializer_factory=={p}")
def mock_incremental_serializer_factory(request: pytest.FixtureRequest, mocker: MockerFixture) -> Callable[[], Any]:
    match getattr(request, "param", None):
        case "buffered":
            return lambda: mocker.NonCallableMagicMock(
                spec=BufferedIncrementalPacketSerializer,
                **{
                    "create_deserializer_buffer.side_effect": lambda sizehint: memoryview(bytearray(sizehint)),
                },
            )
        case None:
            return lambda: mocker.NonCallableMagicMock(spec=AbstractIncrementalPacketSerializer)
        case _:
            pytest.fail("mock_incremental_serializer_factory: Invalid parameter")


@pytest.fixture
def mock_incremental_serializer(mock_incremental_serializer_factory: Callable[[], Any]) -> Any:
    return mock_incremental_serializer_factory()


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
    return lambda: mocker.NonCallableMagicMock(spec=StreamProtocol, **{"buffered_receiver.side_effect": UnsupportedOperation})


@pytest.fixture
def mock_stream_protocol(mock_stream_protocol_factory: Callable[[], Any]) -> Any:
    return mock_stream_protocol_factory()


@pytest.fixture
def mock_buffered_stream_receiver_factory(mocker: MockerFixture) -> Callable[[], Any]:
    return lambda: mocker.NonCallableMagicMock(
        spec=BufferedStreamReceiver,
        **{
            "create_buffer.side_effect": lambda sizehint: memoryview(bytearray(sizehint)),
        },
    )


@pytest.fixture
def mock_buffered_stream_receiver(mock_buffered_stream_receiver_factory: Callable[[], Any]) -> Any:
    return mock_buffered_stream_receiver_factory()
