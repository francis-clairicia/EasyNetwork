# -*- coding: utf-8 -*-

from __future__ import annotations

import pathlib
from socket import AF_INET, IPPROTO_TCP, IPPROTO_UDP, SOCK_DGRAM, SOCK_STREAM, socket as Socket
from ssl import SSLContext, SSLSocket
from typing import TYPE_CHECKING, Any, Callable

from easynetwork.converter import AbstractPacketConverterComposite
from easynetwork.protocol import DatagramProtocol, StreamProtocol
from easynetwork.serializers.abc import AbstractIncrementalPacketSerializer, AbstractPacketSerializer
from easynetwork.tools.stream import StreamDataConsumer, StreamDataProducer

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    directory = pathlib.PurePath(__file__).parent
    for item in items:
        if pathlib.PurePath(item.fspath).is_relative_to(directory):
            item.add_marker(pytest.mark.unit)


@pytest.fixture
def mock_socket_factory(mocker: MockerFixture) -> Callable[[], MagicMock]:
    def factory() -> MagicMock:
        mock_socket = mocker.NonCallableMagicMock(spec=Socket)
        mock_socket.family = AF_INET
        mock_socket.type = -1
        mock_socket.proto = 0
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
        mock_socket.do_handshake.return_value = None
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


@pytest.fixture
def mock_incremental_serializer_factory(mocker: MockerFixture) -> Callable[[], Any]:
    return lambda: mocker.NonCallableMagicMock(spec=AbstractIncrementalPacketSerializer)


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
    return lambda: mocker.NonCallableMagicMock(spec=StreamProtocol)


@pytest.fixture
def mock_stream_protocol(mock_stream_protocol_factory: Callable[[], Any]) -> Any:
    return mock_stream_protocol_factory()


@pytest.fixture
def mock_stream_data_producer_factory(mocker: MockerFixture) -> Callable[[], Any]:
    return lambda: mocker.NonCallableMagicMock(spec=StreamDataProducer)


@pytest.fixture
def mock_stream_data_producer(mock_stream_data_producer_factory: Callable[[], Any]) -> Any:
    return mock_stream_data_producer_factory()


@pytest.fixture
def mock_stream_data_consumer_factory(mocker: MockerFixture) -> Callable[[], Any]:
    return lambda: mocker.NonCallableMagicMock(spec=StreamDataConsumer)


@pytest.fixture
def mock_stream_data_consumer(mock_stream_data_consumer_factory: Callable[[], Any]) -> Any:
    return mock_stream_data_consumer_factory()
